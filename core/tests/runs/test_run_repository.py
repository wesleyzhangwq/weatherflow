from pathlib import Path

import pytest

from weatherflow.runs import (
    DuplicateRunError,
    Run,
    RunRepository,
    RunStatus,
    RunVersionConflict,
    ToolMode,
)
from weatherflow.storage import Database


async def make_repository(tmp_path: Path) -> tuple[Database, RunRepository]:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    return database, RunRepository(database)


async def test_create_round_trips_every_run_field(tmp_path: Path) -> None:
    database, repository = await make_repository(tmp_path)
    run = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
        tool_mode=ToolMode.BYPASS,
    )

    async with database.transaction() as connection:
        await repository.create_in(connection, run)

    assert await repository.get(run.id) == run
    assert await repository.get_by_client_request_id("request-1") == run
    assert run.tool_mode is ToolMode.BYPASS


async def test_duplicate_client_request_id_is_rejected(tmp_path: Path) -> None:
    database, repository = await make_repository(tmp_path)
    first = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    duplicate = Run.new(
        client_request_id="request-1",
        user_intent="another intent",
        workspace_id="workspace-1",
    )

    async with database.transaction() as connection:
        await repository.create_in(connection, first)

    with pytest.raises(DuplicateRunError):
        async with database.transaction() as connection:
            await repository.create_in(connection, duplicate)


async def test_transition_increments_version(tmp_path: Path) -> None:
    database, repository = await make_repository(tmp_path)
    run = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    async with database.transaction() as connection:
        await repository.create_in(connection, run)
        updated = await repository.transition_in(
            connection,
            run.id,
            RunStatus.PLANNING,
            expected_version=0,
        )

    assert updated.status is RunStatus.PLANNING
    assert updated.version == 1
    assert updated.updated_at >= run.updated_at


async def test_stale_version_cannot_overwrite_run(tmp_path: Path) -> None:
    database, repository = await make_repository(tmp_path)
    run = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    async with database.transaction() as connection:
        await repository.create_in(connection, run)
        await repository.transition_in(
            connection,
            run.id,
            RunStatus.PLANNING,
            expected_version=0,
        )

    with pytest.raises(RunVersionConflict):
        async with database.transaction() as connection:
            await repository.transition_in(
                connection,
                run.id,
                RunStatus.RUNNING,
                expected_version=0,
            )

    stored = await repository.get(run.id)
    assert stored is not None
    assert stored.status is RunStatus.PLANNING
    assert stored.version == 1
