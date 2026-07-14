from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest

from weatherflow.automations import (
    AUTOMATION_SCHEMA_SQL,
    Automation,
    AutomationRepository,
    AutomationStatus,
    AutomationVersionConflict,
    ScheduleKind,
    ScheduleSpec,
    TriggerKind,
)
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository


async def setup(tmp_path: Path) -> tuple[Database, Workspace, AutomationRepository]:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    async with database.connect() as connection:
        await connection.executescript(AUTOMATION_SCHEMA_SQL)
        await connection.commit()
    workspace = Workspace.new(
        name="Automations",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await WorkspaceRepository(database).create(workspace)
    return database, workspace, AutomationRepository(database)


def daily() -> ScheduleSpec:
    return ScheduleSpec(
        kind=ScheduleKind.DAILY,
        timezone="UTC",
        at_time=time(8, 0),
    )


async def test_repository_round_trips_and_updates_optimistically(tmp_path: Path) -> None:
    _, workspace, repository = await setup(tmp_path)
    now = datetime(2026, 7, 14, 7, 0, tzinfo=UTC)
    automation = Automation.new(
        workspace_id=workspace.id,
        name="每日简报",
        prompt="整理今天的重点。",
        schedule=daily(),
        now=now,
    )

    await repository.create(automation)
    updated = automation.model_copy(
        update={
            "name": "工作日简报",
            "version": 1,
            "updated_at": now + timedelta(minutes=1),
        }
    )
    await repository.update(updated, expected_version=0)

    assert await repository.get(automation.id) == updated
    assert await repository.list(workspace.id) == [updated]
    with pytest.raises(AutomationVersionConflict):
        await repository.update(updated, expected_version=0)


async def test_claim_due_coalesces_missed_occurrences_and_is_atomic(tmp_path: Path) -> None:
    _, workspace, repository = await setup(tmp_path)
    created_at = datetime(2026, 7, 10, 7, 0, tzinfo=UTC)
    now = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
    automation = Automation.new(
        workspace_id=workspace.id,
        name="每日简报",
        prompt="整理今天的重点。",
        schedule=daily(),
        now=created_at,
    )
    await repository.create(automation)

    first = await repository.claim_scheduled(automation.id, now=now)
    repeated = await repository.claim_scheduled(automation.id, now=now)
    current = await repository.get(automation.id)

    assert first is not None
    assert first.trigger is TriggerKind.SCHEDULED
    assert first.scheduled_for == datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    assert repeated is None
    assert current is not None
    assert current.next_run_at == datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
    assert current.last_run_at == now
    assert current.version == 1
    assert len(await repository.list_history(automation.id)) == 1


async def test_paused_automation_is_not_due_and_deletion_removes_history(tmp_path: Path) -> None:
    _, workspace, repository = await setup(tmp_path)
    now = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
    automation = Automation.new(
        workspace_id=workspace.id,
        name="暂停任务",
        prompt="不要运行。",
        schedule=daily(),
        now=now - timedelta(days=1),
    ).model_copy(update={"status": AutomationStatus.PAUSED})
    await repository.create(automation)

    assert await repository.list_due(now) == []
    assert await repository.claim_scheduled(automation.id, now=now) is None
    await repository.delete(automation.id, expected_version=0)
    assert await repository.get(automation.id) is None
