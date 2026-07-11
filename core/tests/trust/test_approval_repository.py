from pathlib import Path

import pytest

from weatherflow.capabilities import ToolEffect
from weatherflow.runs import Run, RunRepository
from weatherflow.storage import Database
from weatherflow.trust import (
    Action,
    ActionRepository,
    Approval,
    ApprovalRepository,
    ApprovalStatus,
    ApprovalVersionConflict,
    DuplicateApprovalError,
)


async def setup_repository(
    tmp_path: Path,
) -> tuple[Database, ApprovalRepository, Action]:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    run = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    action = Action.new(
        run_id=run.id,
        tool_id="github.create_release",
        arguments={},
        effect=ToolEffect.EXTERNAL_WRITE,
        idempotency_key="action-1",
        preview={},
    )
    async with database.transaction() as connection:
        await RunRepository(database).create_in(connection, run)
        await ActionRepository(database).create_in(connection, action)
    return database, ApprovalRepository(database), action


async def test_create_round_trip_and_action_lookup(tmp_path: Path) -> None:
    database, repository, action = await setup_repository(tmp_path)
    approval = Approval.for_action(action)

    async with database.transaction() as connection:
        await repository.create_in(connection, approval)

    assert await repository.get(approval.id) == approval
    assert await repository.get_by_action_id(action.id) == approval


async def test_duplicate_approval_for_action_is_rejected(tmp_path: Path) -> None:
    database, repository, action = await setup_repository(tmp_path)
    first = Approval.for_action(action)
    duplicate = Approval.for_action(action)
    async with database.transaction() as connection:
        await repository.create_in(connection, first)

    with pytest.raises(DuplicateApprovalError):
        async with database.transaction() as connection:
            await repository.create_in(connection, duplicate)


async def test_decision_is_versioned_and_attributed(tmp_path: Path) -> None:
    database, repository, action = await setup_repository(tmp_path)
    approval = Approval.for_action(action)
    async with database.transaction() as connection:
        await repository.create_in(connection, approval)
        updated = await repository.transition_in(
            connection,
            approval.id,
            ApprovalStatus.APPROVED,
            expected_version=0,
            decided_by="user",
            rationale="Ship it",
        )

    assert updated.status is ApprovalStatus.APPROVED
    assert updated.version == 1
    assert updated.decided_at is not None
    assert updated.decided_by == "user"
    assert updated.rationale == "Ship it"


async def test_stale_version_cannot_overwrite_approval(tmp_path: Path) -> None:
    database, repository, action = await setup_repository(tmp_path)
    approval = Approval.for_action(action)
    async with database.transaction() as connection:
        await repository.create_in(connection, approval)
        await repository.transition_in(
            connection,
            approval.id,
            ApprovalStatus.APPROVED,
            expected_version=0,
            decided_by="user",
        )

    with pytest.raises(ApprovalVersionConflict):
        async with database.transaction() as connection:
            await repository.transition_in(
                connection,
                approval.id,
                ApprovalStatus.DENIED,
                expected_version=0,
                decided_by="user",
            )

    stored = await repository.get(approval.id)
    assert stored is not None
    assert stored.status is ApprovalStatus.APPROVED
    assert stored.version == 1
