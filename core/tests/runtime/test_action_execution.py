import asyncio
from pathlib import Path

import aiosqlite
import pytest

from weatherflow.capabilities import ToolEffect, ToolSpec
from weatherflow.events import Event, EventLedger
from weatherflow.runs import RunCoordinator, RunRepository, RunStatus
from weatherflow.runtime import (
    ActionExecutionCoordinator,
    ActionExecutionStatus,
    DefinitiveToolError,
    ToolExecutionResult,
)
from weatherflow.storage import Database
from weatherflow.trust import (
    Action,
    ActionRepository,
    ActionStatus,
    ApprovalPolicyError,
    SupervisedPolicy,
)
from weatherflow.workspaces import Workspace


class Executor:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def execute(self, tool, arguments, context):
        self.calls.append((tool, arguments, context))
        if self.error:
            raise self.error
        return ToolExecutionResult(output={"release_url": "https://example.test/v3"})


class BlockingExecutor:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def execute(self, tool, arguments, context):
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class InvalidOutputExecutor:
    def __init__(self) -> None:
        self.calls = []

    async def execute(self, tool, arguments, context):
        self.calls.append((tool, arguments, context))
        return ToolExecutionResult(
            output={"release_url": 42, "credential": "must-not-be-persisted"}
        )


def external_tool() -> ToolSpec:
    return ToolSpec(
        tool_id="github.create_release",
        description="Create release",
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"tag": {"type": "string"}},
            "additionalProperties": False,
        },
        output_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"release_url": {"type": "string"}},
            "required": ["release_url"],
            "additionalProperties": False,
        },
        effect=ToolEffect.EXTERNAL_WRITE,
        required_scopes=frozenset({"github:write"}),
        source="test",
        source_version="1",
    )


async def setup(tmp_path: Path, ledger_type=EventLedger, *, approved=True):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    ledger = ledger_type(database)
    runs = RunRepository(database)
    run_coordinator = RunCoordinator(database, runs, ledger)
    run = await run_coordinator.create_run(
        client_request_id="request-1", user_intent="ship", workspace_id="workspace-1"
    )
    run = await run_coordinator.transition(
        run_id=run.id, target=RunStatus.PLANNING, expected_version=run.version
    )
    run = await run_coordinator.transition(
        run_id=run.id, target=RunStatus.RUNNING, expected_version=run.version
    )
    actions = ActionRepository(database)
    action = Action.new(
        run_id=run.id,
        tool_id="github.create_release",
        arguments={"tag": "v3"},
        effect=ToolEffect.EXTERNAL_WRITE,
        idempotency_key="release-v3",
        preview={},
    )
    async with database.transaction() as connection:
        await actions.create_in(connection, action)
        if approved:
            action = await actions.transition_in(connection, action.id, ActionStatus.APPROVED, 0)
    workspace = Workspace.new(
        name="WeatherFlow",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
        granted_scopes={"github:write"},
    )
    coordinator = ActionExecutionCoordinator(
        database=database,
        actions=actions,
        runs=runs,
        run_coordinator=run_coordinator,
        ledger=ledger,
        policy=SupervisedPolicy(),
    )
    return coordinator, actions, runs, action, workspace


async def test_approved_action_executes_once_and_succeeds(tmp_path: Path) -> None:
    coordinator, _, _, action, workspace = await setup(tmp_path)
    executor = Executor()

    outcome = await coordinator.execute(
        action_id=action.id, tool=external_tool(), workspace=workspace, executor=executor
    )

    assert outcome.status is ActionExecutionStatus.SUCCEEDED
    assert outcome.action.status is ActionStatus.SUCCEEDED
    assert len(executor.calls) == 1


async def test_side_effect_output_schema_failure_routes_action_and_run_to_review(
    tmp_path: Path,
) -> None:
    coordinator, actions, runs, action, workspace = await setup(tmp_path)
    executor = InvalidOutputExecutor()

    outcome = await coordinator.execute(
        action_id=action.id,
        tool=external_tool(),
        workspace=workspace,
        executor=executor,
    )

    assert outcome.status is ActionExecutionStatus.NEEDS_REVIEW
    assert len(executor.calls) == 1
    stored_action = await actions.get(action.id)
    stored_run = await runs.get(action.run_id)
    assert stored_action is not None and stored_action.status is ActionStatus.NEEDS_REVIEW
    assert stored_action.result is None
    assert "must-not-be-persisted" not in str(stored_action)
    assert stored_run is not None and stored_run.status is RunStatus.NEEDS_REVIEW


async def test_unapproved_or_out_of_scope_action_never_executes(tmp_path: Path) -> None:
    coordinator, _, _, action, workspace = await setup(tmp_path, approved=False)
    executor = Executor()

    with pytest.raises(ApprovalPolicyError):
        await coordinator.execute(
            action_id=action.id,
            tool=external_tool(),
            workspace=workspace,
            executor=executor,
        )
    assert executor.calls == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (DefinitiveToolError("rejected"), ActionExecutionStatus.FAILED),
        (RuntimeError("connection lost"), ActionExecutionStatus.NEEDS_REVIEW),
    ],
)
async def test_execution_errors_are_classified(tmp_path: Path, error, expected) -> None:
    coordinator, _, runs, action, workspace = await setup(tmp_path)

    outcome = await coordinator.execute(
        action_id=action.id,
        tool=external_tool(),
        workspace=workspace,
        executor=Executor(error),
    )

    assert outcome.status is expected
    if expected is ActionExecutionStatus.NEEDS_REVIEW:
        run = await runs.get(action.run_id)
        assert run is not None and run.status is RunStatus.NEEDS_REVIEW


async def test_recovering_executing_action_never_calls_executor(tmp_path: Path) -> None:
    coordinator, actions, runs, action, workspace = await setup(tmp_path)
    async with coordinator.database.transaction() as connection:
        action = await actions.transition_in(
            connection, action.id, ActionStatus.EXECUTING, action.version
        )
    executor = Executor()

    outcome = await coordinator.execute(
        action_id=action.id, tool=external_tool(), workspace=workspace, executor=executor
    )

    assert outcome.status is ActionExecutionStatus.NEEDS_REVIEW
    assert executor.calls == []
    run = await runs.get(action.run_id)
    assert run is not None and run.status is RunStatus.NEEDS_REVIEW


async def test_timeout_during_side_effect_routes_action_and_run_to_review(tmp_path: Path) -> None:
    coordinator, actions, runs, action, workspace = await setup(tmp_path)

    outcome = await coordinator.execute(
        action_id=action.id,
        tool=external_tool().model_copy(update={"timeout_seconds": 1}),
        workspace=workspace,
        executor=BlockingExecutor(),
    )

    assert outcome.status is ActionExecutionStatus.NEEDS_REVIEW
    stored_action = await actions.get(action.id)
    stored_run = await runs.get(action.run_id)
    assert stored_action is not None and stored_action.status is ActionStatus.NEEDS_REVIEW
    assert stored_run is not None and stored_run.status is RunStatus.NEEDS_REVIEW
    assert "timed out" in (outcome.error or "")


async def test_cancellation_during_side_effect_cannot_leave_action_executing(
    tmp_path: Path,
) -> None:
    coordinator, actions, runs, action, workspace = await setup(tmp_path)
    executor = BlockingExecutor()
    execution = asyncio.create_task(
        coordinator.execute(
            action_id=action.id,
            tool=external_tool(),
            workspace=workspace,
            executor=executor,
        )
    )
    await executor.started.wait()

    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution

    stored_action = await actions.get(action.id)
    stored_run = await runs.get(action.run_id)
    assert stored_action is not None and stored_action.status is ActionStatus.NEEDS_REVIEW
    assert stored_run is not None and stored_run.status is RunStatus.NEEDS_REVIEW


class FailingLedger(EventLedger):
    async def append_in(self, connection: aiosqlite.Connection, event: Event) -> None:
        if event.type == "action.execution_started":
            raise RuntimeError("ledger failed")
        await super().append_in(connection, event)


async def test_start_audit_failure_rolls_back_before_executor(tmp_path: Path) -> None:
    coordinator, actions, _, action, workspace = await setup(tmp_path, FailingLedger)
    executor = Executor()

    with pytest.raises(RuntimeError, match="ledger failed"):
        await coordinator.execute(
            action_id=action.id,
            tool=external_tool(),
            workspace=workspace,
            executor=executor,
        )

    assert executor.calls == []
    assert await actions.get(action.id) == action
