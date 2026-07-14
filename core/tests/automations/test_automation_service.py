import asyncio
from datetime import UTC, datetime, time
from pathlib import Path

from pydantic import ValidationError

from weatherflow.automations import (
    AUTOMATION_SCHEMA_SQL,
    AutomationRepository,
    AutomationScheduler,
    AutomationService,
    AutomationStatus,
    RunLinkStatus,
    ScheduleKind,
    ScheduleSpec,
)
from weatherflow.runs import Run, RunRepository
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


async def setup(tmp_path: Path, clock: MutableClock):
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
    runs = RunRepository(database)
    submissions: list[dict[str, str]] = []

    async def submit_run(*, user_intent: str, client_request_id: str, workspace_id: str) -> str:
        submissions.append(
            {
                "user_intent": user_intent,
                "client_request_id": client_request_id,
                "workspace_id": workspace_id,
            }
        )
        existing = await runs.get_by_client_request_id(client_request_id)
        if existing is not None:
            return existing.id
        run = Run.new(
            client_request_id=client_request_id,
            user_intent=user_intent,
            workspace_id=workspace_id,
        )
        async with database.transaction() as connection:
            await runs.create_in(connection, run)
        return run.id

    repository = AutomationRepository(database)
    service = AutomationService(repository=repository, submit_run=submit_run, now=clock)
    return workspace, repository, service, submissions


def daily() -> ScheduleSpec:
    return ScheduleSpec(
        kind=ScheduleKind.DAILY,
        timezone="UTC",
        at_time=time(8, 0),
    )


async def test_service_manages_lifecycle_and_manual_run(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 7, 14, 7, 0, tzinfo=UTC))
    workspace, _, service, submissions = await setup(tmp_path, clock)
    automation = await service.create(
        workspace_id=workspace.id,
        name="每日简报",
        prompt="整理今天的重点。",
        schedule=daily(),
    )
    paused = await service.pause(automation.id, expected_version=automation.version)
    resumed = await service.resume(paused.id, expected_version=paused.version)
    edited = await service.update(
        resumed.id,
        expected_version=resumed.version,
        name="每日状态简报",
        prompt="只总结高信号事项。",
    )

    link = await service.run_now(edited.id)

    assert paused.status is AutomationStatus.PAUSED
    assert resumed.status is AutomationStatus.ENABLED
    assert edited.name == "每日状态简报"
    assert link.status is RunLinkStatus.SUBMITTED
    assert link.run_id is not None
    assert submissions == [
        {
            "user_intent": "只总结高信号事项。",
            "client_request_id": link.client_request_id,
            "workspace_id": workspace.id,
        }
    ]
    assert await service.history(edited.id) == [link]
    latest = await service.get(edited.id)
    assert latest is not None
    await service.delete(edited.id, expected_version=latest.version)
    assert await service.get(edited.id) is None


async def test_service_revalidates_edits_instead_of_bypassing_domain_constraints(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 7, 14, 7, 0, tzinfo=UTC))
    workspace, _, service, _ = await setup(tmp_path, clock)
    automation = await service.create(
        workspace_id=workspace.id,
        name="有效名称",
        prompt="有效指令。",
        schedule=daily(),
    )

    try:
        await service.update(
            automation.id,
            expected_version=automation.version,
            name="",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("empty automation name must be rejected")


async def test_tick_coalesces_startup_backlog_to_one_normal_run(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 7, 10, 7, 0, tzinfo=UTC))
    workspace, repository, service, submissions = await setup(tmp_path, clock)
    automation = await service.create(
        workspace_id=workspace.id,
        name="每日简报",
        prompt="整理今天的重点。",
        schedule=daily(),
    )
    clock.value = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)

    first = await service.tick()
    second = await service.tick()

    assert len(first) == 1
    assert second == []
    assert len(submissions) == 1
    current = await repository.get(automation.id)
    assert current is not None
    assert current.next_run_at == datetime(2026, 7, 15, 8, 0, tzinfo=UTC)


async def test_pending_submission_recovery_reuses_idempotency_key(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 7, 14, 9, 0, tzinfo=UTC))
    workspace, repository, service, submissions = await setup(tmp_path, clock)
    automation = await service.create(
        workspace_id=workspace.id,
        name="恢复任务",
        prompt="恢复后运行。",
        schedule=daily(),
    )
    link = await repository.claim_manual(automation.id, now=clock())

    recovered = await service.recover_pending()
    repeated = await service.recover_pending()

    assert [item.id for item in recovered] == [link.id]
    assert repeated == []
    assert submissions[0]["client_request_id"] == link.client_request_id


async def test_scheduler_start_stop_owns_one_polling_task(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 7, 14, 7, 0, tzinfo=UTC))
    workspace, _, service, submissions = await setup(tmp_path, clock)
    await service.create(
        workspace_id=workspace.id,
        name="定时任务",
        prompt="运行。",
        schedule=daily(),
    )
    clock.value = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
    scheduler = AutomationScheduler(service=service, interval_seconds=0.01)

    await scheduler.start()
    for _ in range(50):
        if submissions:
            break
        await asyncio.sleep(0.01)
    await scheduler.stop()

    assert len(submissions) == 1
    assert scheduler.running is False
