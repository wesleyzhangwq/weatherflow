from pathlib import Path

import pytest

from weatherflow.runs import Run, RunRepository
from weatherflow.runtime import (
    AgentMessage,
    CheckpointVersionConflict,
    DuplicateCheckpointError,
    MessageRole,
    RunCheckpoint,
    RunCheckpointRepository,
)
from weatherflow.storage import Database


async def setup(tmp_path: Path):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    run = Run.new(
        client_request_id="request-1",
        user_intent="answer question",
        workspace_id="workspace-1",
    )
    async with database.transaction() as connection:
        await RunRepository(database).create_in(connection, run)
    return database, RunCheckpointRepository(database), run


async def test_create_and_get_round_trip_serializable_state(tmp_path: Path) -> None:
    database, repository, run = await setup(tmp_path)
    checkpoint = RunCheckpoint.new(
        run_id=run.id,
        transcript=(AgentMessage(role=MessageRole.USER, content="Hello"),),
        state={"phase": "planning", "artifact_ids": ["artifact-1"]},
    )

    async with database.transaction() as connection:
        await repository.create_in(connection, checkpoint)

    assert checkpoint.version == 0
    assert await repository.get(run.id) == checkpoint

    with pytest.raises(DuplicateCheckpointError):
        async with database.transaction() as connection:
            await repository.create_in(connection, checkpoint)


async def test_save_is_optimistic_and_round_trips_transcript(tmp_path: Path) -> None:
    database, repository, run = await setup(tmp_path)
    checkpoint = RunCheckpoint.new(run_id=run.id)
    async with database.transaction() as connection:
        await repository.create_in(connection, checkpoint)
        desired = checkpoint.model_copy(
            update={
                "step_index": 1,
                "transcript": (AgentMessage(role=MessageRole.ASSISTANT, content="Done"),),
                "state": {"complete": True},
            }
        )
        saved = await repository.save_in(connection, desired, expected_version=0)

    assert saved.version == 1
    assert saved.step_index == 1
    assert saved.transcript[0].content == "Done"
    assert saved.state == {"complete": True}

    with pytest.raises(CheckpointVersionConflict):
        async with database.transaction() as connection:
            await repository.save_in(connection, desired, expected_version=0)

    assert await repository.get(run.id) == saved
