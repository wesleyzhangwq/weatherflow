from pathlib import Path

import aiosqlite
import pytest

from weatherflow.capabilities import ToolEffect, ToolSpec
from weatherflow.events import Event, EventLedger
from weatherflow.runs import RunCoordinator, RunRepository, RunStatus
from weatherflow.storage import Database
from weatherflow.trust import (
    ActionRepository,
    ActionStatus,
    ApprovalCoordinator,
    ApprovalPolicyError,
    ApprovalRepository,
    ApprovalStateError,
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
    ("run_id_override", "tool_override", "arguments_override"),
    [
        ("another-run", None, None),
        (None, release_tool().model_copy(update={"tool_id": "github.create_tag"}), None),
        (None, None, {"tag": "v4.0.0"}),
    ],
)
async def test_idempotency_key_cannot_reuse_a_different_action_identity(
    tmp_path: Path,
    run_id_override: str | None,
    tool_override: ToolSpec | None,
    arguments_override: dict[str, str] | None,
) -> None:
    coordinator, _, _, workspace, run_id = await setup_coordinator(tmp_path)
    values = {
        "run_id": run_id,
        "expected_run_version": 2,
        "tool": release_tool(),
        "workspace": workspace,
        "arguments": {"tag": "v3.0.0"},
        "idempotency_key": "run-1:release-v3",
        "preview": {"summary": "Create release v3.0.0"},
    }
    await coordinator.propose(**values)

    with pytest.raises(ApprovalStateError, match="idempotency key identity mismatch"):
        await coordinator.propose(
            **{
                **values,
                "run_id": run_id_override or run_id,
                "tool": tool_override or release_tool(),
                "arguments": arguments_override or {"tag": "v3.0.0"},
            }
        )


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


async def propose_release(tmp_path: Path):
    coordinator, ledger, runs, workspace, run_id = await setup_coordinator(tmp_path)
    bundle = await coordinator.propose(
        run_id=run_id,
        expected_run_version=2,
        tool=release_tool(),
        workspace=workspace,
        arguments={"tag": "v3.0.0"},
        idempotency_key="run-1:release-v3",
        preview={"summary": "Create release v3.0.0"},
    )
    return coordinator, ledger, runs, bundle


async def test_approve_resumes_run_without_executing_action(tmp_path: Path) -> None:
    coordinator, _, _, proposed = await propose_release(tmp_path)

    decided = await coordinator.decide(
        approval_id=proposed.approval.id,
        expected_version=0,
        approved=True,
        decided_by="user",
        rationale="Ship it",
    )

    assert decided.approval.status is ApprovalStatus.APPROVED
    assert decided.action.status is ActionStatus.APPROVED
    assert decided.run.status is RunStatus.RUNNING
    assert decided.action.status is not ActionStatus.EXECUTING

    repeated = await coordinator.decide(
        approval_id=proposed.approval.id,
        expected_version=0,
        approved=True,
        decided_by="user",
        rationale="retry",
    )
    assert repeated == decided


async def test_deny_resumes_run_with_terminal_action(tmp_path: Path) -> None:
    coordinator, _, _, proposed = await propose_release(tmp_path)

    decided = await coordinator.decide(
        approval_id=proposed.approval.id,
        expected_version=0,
        approved=False,
        decided_by="user",
        rationale="Not now",
    )

    assert decided.approval.status is ApprovalStatus.DENIED
    assert decided.action.status is ActionStatus.DENIED
    assert decided.run.status is RunStatus.RUNNING


async def test_expiry_cancels_action_and_suspends_run(tmp_path: Path) -> None:
    coordinator, _, _, proposed = await propose_release(tmp_path)

    expired = await coordinator.expire(
        approval_id=proposed.approval.id,
        expected_version=0,
    )

    assert expired.approval.status is ApprovalStatus.EXPIRED
    assert expired.action.status is ActionStatus.CANCELLED
    assert expired.run.status is RunStatus.PAUSED


class FailingLedger(EventLedger):
    async def append_in(self, connection: aiosqlite.Connection, event: Event) -> None:
        raise RuntimeError("ledger failed")


async def test_decision_audit_failure_rolls_back_every_record(tmp_path: Path) -> None:
    coordinator, ledger, runs, proposed = await propose_release(tmp_path)
    failing_ledger = FailingLedger(coordinator.database)
    failing = ApprovalCoordinator(
        database=coordinator.database,
        actions=coordinator.actions,
        approvals=coordinator.approvals,
        runs=runs,
        run_coordinator=RunCoordinator(coordinator.database, runs, failing_ledger),
        ledger=failing_ledger,
        policy=coordinator.policy,
    )
    before = await ledger.list_correlation(proposed.run.id)

    with pytest.raises(RuntimeError, match="ledger failed"):
        await failing.decide(
            approval_id=proposed.approval.id,
            expected_version=0,
            approved=True,
            decided_by="user",
        )

    action = await coordinator.actions.get(proposed.action.id)
    approval = await coordinator.approvals.get(proposed.approval.id)
    run = await runs.get(proposed.run.id)
    assert action == proposed.action
    assert approval == proposed.approval
    assert run == proposed.run
    assert await ledger.list_correlation(proposed.run.id) == before
