from pathlib import Path

import pytest

from weatherflow.capabilities import ToolEffect, ToolSpec
from weatherflow.events import EventLedger
from weatherflow.runs import RunCoordinator, RunRepository, RunStatus
from weatherflow.storage import Database
from weatherflow.trust import (
    ActionRepository,
    ApprovalCoordinator,
    ApprovalPolicyError,
    ApprovalRepository,
    ApprovalStatus,
    SupervisedPolicy,
)
from weatherflow.workspaces import Workspace


async def setup_coordinator(
    tmp_path: Path,
) -> tuple[ApprovalCoordinator, EventLedger, RunRepository, Workspace, str]:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    ledger = EventLedger(database)
    runs = RunRepository(database)
    run_coordinator = RunCoordinator(database, runs, ledger)
    run = await run_coordinator.create_run(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    run = await run_coordinator.transition(
        run_id=run.id,
        target=RunStatus.PLANNING,
        expected_version=run.version,
    )
    run = await run_coordinator.transition(
        run_id=run.id,
        target=RunStatus.RUNNING,
        expected_version=run.version,
    )
    workspace = Workspace.new(
        name="WeatherFlow",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
        granted_scopes={"github:write"},
    )
    coordinator = ApprovalCoordinator(
        database=database,
        actions=ActionRepository(database),
        approvals=ApprovalRepository(database),
        runs=runs,
        run_coordinator=run_coordinator,
        ledger=ledger,
        policy=SupervisedPolicy(),
    )
    return coordinator, ledger, runs, workspace, run.id


def release_tool(*, effect: ToolEffect = ToolEffect.EXTERNAL_WRITE) -> ToolSpec:
    return ToolSpec(
        tool_id="github.create_release",
        description="Create a GitHub release",
        input_schema={},
        output_schema={},
        effect=effect,
        required_scopes=frozenset({"github:write"}),
        source="builtin",
        source_version="1",
    )


async def test_proposal_is_persisted_before_run_waits(tmp_path: Path) -> None:
    coordinator, ledger, _, workspace, run_id = await setup_coordinator(tmp_path)

    bundle = await coordinator.propose(
        run_id=run_id,
        expected_run_version=2,
        tool=release_tool(),
        workspace=workspace,
        arguments={"tag": "v3.0.0"},
        idempotency_key="run-1:release-v3",
        preview={"summary": "Create release v3.0.0"},
    )

    assert bundle.action.status.value == "proposed"
    assert bundle.approval.status is ApprovalStatus.PENDING
    assert bundle.run.status is RunStatus.WAITING_APPROVAL
    event_types = [event.type for event in await ledger.list_correlation(run_id)]
    assert event_types[-3:] == [
        "action.proposed",
        "approval.requested",
        "run.status_changed",
    ]


async def test_repeated_idempotency_key_returns_existing_bundle(tmp_path: Path) -> None:
    coordinator, ledger, _, workspace, run_id = await setup_coordinator(tmp_path)
    values = {
        "run_id": run_id,
        "expected_run_version": 2,
        "tool": release_tool(),
        "workspace": workspace,
        "arguments": {"tag": "v3.0.0"},
        "idempotency_key": "run-1:release-v3",
        "preview": {"summary": "Create release v3.0.0"},
    }
    first = await coordinator.propose(**values)
    before = await ledger.list_correlation(run_id)

    repeated = await coordinator.propose(**values)

    assert repeated == first
    assert await ledger.list_correlation(run_id) == before


@pytest.mark.parametrize(
    ("tool", "scope"),
    [
        (release_tool(), frozenset()),
        (release_tool(effect=ToolEffect.OBSERVE), frozenset({"github:write"})),
    ],
)
async def test_non_approval_policy_decision_changes_nothing(
    tmp_path: Path, tool: ToolSpec, scope: frozenset[str]
) -> None:
    coordinator, ledger, runs, workspace, run_id = await setup_coordinator(tmp_path)
    workspace = workspace.model_copy(update={"granted_scopes": scope})
    before = await ledger.list_correlation(run_id)

    with pytest.raises(ApprovalPolicyError):
        await coordinator.propose(
            run_id=run_id,
            expected_run_version=2,
            tool=tool,
            workspace=workspace,
            arguments={},
            idempotency_key="rejected",
            preview={},
        )

    stored = await runs.get(run_id)
    assert stored is not None
    assert stored.status is RunStatus.RUNNING
    assert await ledger.list_correlation(run_id) == before
