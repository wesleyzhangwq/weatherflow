from pathlib import Path

import pytest

from weatherflow.events import EventLedger
from weatherflow.runs import Run, RunRepository, RunStatus
from weatherflow.runtime import (
    AgentMessage,
    MessageRole,
    RunCheckpoint,
    RunCheckpointRepository,
    RunControlCoordinator,
    RunControlKind,
    RunControlRejectedError,
    RunControlRepository,
    RunControlStatus,
)
from weatherflow.storage import Database


async def setup_control_runtime(tmp_path: Path, *, status: RunStatus = RunStatus.QUEUED):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    run = Run.new(
        client_request_id="control-request",
        user_intent="Initial objective",
        workspace_id="workspace-1",
    ).model_copy(update={"status": status})
    runs = RunRepository(database)
    checkpoints = RunCheckpointRepository(database)
    controls = RunControlRepository(database)
    ledger = EventLedger(database)
    async with database.transaction() as connection:
        await runs.create_in(connection, run)
        await checkpoints.create_in(
            connection,
            RunCheckpoint.new(
                run_id=run.id,
                transcript=(AgentMessage(role=MessageRole.USER, content=run.user_intent),),
            ),
        )
    coordinator = RunControlCoordinator(
        database=database,
        runs=runs,
        controls=controls,
        checkpoints=checkpoints,
        ledger=ledger,
    )
    return run, checkpoints, controls, coordinator, ledger


async def test_steering_is_applied_once_at_the_next_model_boundary(tmp_path: Path) -> None:
    run, checkpoints, controls, coordinator, ledger = await setup_control_runtime(tmp_path)
    control = await coordinator.enqueue(
        run_id=run.id,
        kind=RunControlKind.STEER,
        content="Inspect the tests before changing code.",
    )
    checkpoint = await checkpoints.get(run.id)
    assert checkpoint is not None

    applied = await coordinator.apply_before_model(checkpoint)
    replay_attempt = await coordinator.apply_before_model(applied)

    assert applied.version == checkpoint.version + 1
    assert applied.transcript[-1] == AgentMessage(
        role=MessageRole.USER,
        content="Inspect the tests before changing code.",
    )
    assert replay_attempt == applied
    stored = await controls.get(control.id)
    assert stored is not None
    assert stored.status is RunControlStatus.APPLIED
    assert stored.applied_step_index == applied.step_index
    timeline = await ledger.list_correlation(run.id, limit=100)
    assert [event.type for event in timeline] == [
        "runtime.control_queued",
        "runtime.control_applied",
    ]
    assert "Inspect the tests" not in str(timeline)


async def test_final_boundary_applies_follow_up_and_clears_pending_final_atomically(
    tmp_path: Path,
) -> None:
    run, checkpoints, controls, coordinator, _ = await setup_control_runtime(tmp_path)
    follow_up = await coordinator.enqueue(
        run_id=run.id,
        kind=RunControlKind.FOLLOW_UP,
        content="Now make the answer concise.",
    )
    checkpoint = await checkpoints.get(run.id)
    assert checkpoint is not None
    pending = checkpoint.model_copy(
        update={
            "transcript": checkpoint.transcript
            + (AgentMessage(role=MessageRole.ASSISTANT, content="First answer"),),
            "state": {"pending_turn": {"kind": "final", "content": "First answer"}},
        }
    )
    async with coordinator.database.transaction() as connection:
        pending = await checkpoints.save_in(
            connection,
            pending,
            expected_version=checkpoint.version,
        )

    async with coordinator.database.transaction() as connection:
        applied = await coordinator.apply_at_final_boundary_in(connection, pending)

    assert applied is not None
    assert "pending_turn" not in applied.state
    assert [message.role for message in applied.transcript[-2:]] == [
        MessageRole.ASSISTANT,
        MessageRole.USER,
    ]
    assert applied.transcript[-1].content == "Now make the answer concise."
    stored = await controls.get(follow_up.id)
    assert stored is not None and stored.status is RunControlStatus.APPLIED


async def test_terminal_run_rejects_new_control_without_persisting_it(tmp_path: Path) -> None:
    run, _, controls, coordinator, _ = await setup_control_runtime(
        tmp_path,
        status=RunStatus.SUCCEEDED,
    )

    with pytest.raises(RunControlRejectedError):
        await coordinator.enqueue(
            run_id=run.id,
            kind=RunControlKind.STEER,
            content="Too late",
        )

    assert await controls.list_pending(run.id) == []
