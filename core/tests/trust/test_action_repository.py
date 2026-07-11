from pathlib import Path

import pytest

from weatherflow.capabilities import ToolEffect
from weatherflow.runs import Run, RunRepository
from weatherflow.storage import Database
from weatherflow.trust import (
    Action,
    ActionRepository,
    ActionStatus,
    ActionVersionConflict,
    DuplicateActionError,
)


async def setup_repository(
    tmp_path: Path,
) -> tuple[Database, ActionRepository, Run]:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    run = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    async with database.transaction() as connection:
        await RunRepository(database).create_in(connection, run)
    return database, ActionRepository(database), run


def make_action(run: Run, key: str = "action-1") -> Action:
    return Action.new(
        run_id=run.id,
        tool_id="github.create_release",
        arguments={"tag": "v3.0.0"},
        effect=ToolEffect.EXTERNAL_WRITE,
        idempotency_key=key,
        preview={"summary": "Create release"},
    )


async def test_create_round_trip_and_idempotency_lookup(tmp_path: Path) -> None:
    database, repository, run = await setup_repository(tmp_path)
    action = make_action(run)

    async with database.transaction() as connection:
        await repository.create_in(connection, action)

    assert await repository.get(action.id) == action
    assert await repository.get_by_idempotency_key("action-1") == action


async def test_duplicate_idempotency_key_is_rejected(tmp_path: Path) -> None:
    database, repository, run = await setup_repository(tmp_path)
    first = make_action(run)
    duplicate = make_action(run)
    async with database.transaction() as connection:
        await repository.create_in(connection, first)

    with pytest.raises(DuplicateActionError):
        async with database.transaction() as connection:
            await repository.create_in(connection, duplicate)


async def test_transition_is_versioned(tmp_path: Path) -> None:
    database, repository, run = await setup_repository(tmp_path)
    action = make_action(run)
    async with database.transaction() as connection:
        await repository.create_in(connection, action)
        updated = await repository.transition_in(
            connection,
            action.id,
            ActionStatus.APPROVED,
            expected_version=0,
        )

    assert updated.status is ActionStatus.APPROVED
    assert updated.version == 1


async def test_stale_version_cannot_overwrite_action(tmp_path: Path) -> None:
    database, repository, run = await setup_repository(tmp_path)
    action = make_action(run)
    async with database.transaction() as connection:
        await repository.create_in(connection, action)
        await repository.transition_in(
            connection,
            action.id,
            ActionStatus.APPROVED,
            expected_version=0,
        )

    with pytest.raises(ActionVersionConflict):
        async with database.transaction() as connection:
            await repository.transition_in(
                connection,
                action.id,
                ActionStatus.EXECUTING,
                expected_version=0,
            )

    stored = await repository.get(action.id)
    assert stored is not None
    assert stored.status is ActionStatus.APPROVED
    assert stored.version == 1
