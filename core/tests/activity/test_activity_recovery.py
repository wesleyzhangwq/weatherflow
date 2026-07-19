from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from weatherflow.activity import (
    ActivityReconciliationResult,
    ActivityRecoveryCoordinator,
    ActivityRepository,
    ActivitySourceHealth,
    ActivitySourceState,
    ActivityWatchBucket,
    ActivityWatchDiscovery,
    ActivityWatchInfo,
    ActivityWindowPlanner,
    SummaryTaskStatus,
    SummaryTaskType,
    category_rule_version,
)
from weatherflow.storage import Database

SHANGHAI = ZoneInfo("Asia/Shanghai")


def local(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
) -> datetime:
    return datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=SHANGHAI,
    ).astimezone(UTC)


class DiscoveryClient:
    def __init__(self, *, data_start: datetime, data_end: datetime) -> None:
        rules = category_rule_version([])
        self.discovery = ActivityWatchDiscovery(
            info=ActivityWatchInfo(
                hostname="host",
                version="v0.13.1",
                device_id="device",
            ),
            buckets=(
                ActivityWatchBucket(
                    id="window",
                    type="currentwindow",
                    client="aw-watcher-window",
                    hostname="host",
                    metadata={"start": data_start, "end": data_end},
                ),
                ActivityWatchBucket(
                    id="afk",
                    type="afkstatus",
                    client="aw-watcher-afk",
                    hostname="host",
                    metadata={"start": data_start, "end": data_end},
                ),
            ),
            data_start=data_start,
            data_end=data_end,
            settings={"classes": []},
            category_rules=rules,
        )

    async def discover(self):
        return self.discovery


class NoopSummaries:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute_task(self, task_id, **_arguments):
        self.calls.append(task_id)
        raise AssertionError("prepare must not execute summary models")


class RecordingPlanner(ActivityWindowPlanner):
    def __init__(self) -> None:
        self.data_starts: list[datetime] = []

    def expected_windows(
        self,
        *,
        data_start: datetime,
        now: datetime,
        data_end: datetime | None = None,
    ):
        del now, data_end
        self.data_starts.append(data_start)
        return []


class RecordingRepository(ActivityRepository):
    def __init__(self, database: Database) -> None:
        super().__init__(database)
        self.task_id_candidates: list[set[str] | None] = []

    async def task_ids(
        self,
        *,
        candidate_ids: set[str] | None = None,
    ) -> set[str]:
        self.task_id_candidates.append(candidate_ids)
        return await super().task_ids(candidate_ids=candidate_ids)


async def repository(tmp_path: Path) -> ActivityRepository:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    return ActivityRepository(database)


async def test_prepare_enumerates_theoretical_windows_beyond_last_event(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path)
    summaries = NoopSummaries()
    coordinator = ActivityRecoveryCoordinator(
        client=DiscoveryClient(
            data_start=local(2026, 7, 15),
            data_end=local(2026, 7, 15, 1),
        ),
        repository=store,
        summaries=summaries,
    )

    result = await coordinator.prepare(now=local(2026, 7, 16, 7))
    expected = ActivityWindowPlanner().task_id(
        SummaryTaskType.STAGE_6H,
        window_start=local(2026, 7, 16),
        window_end=local(2026, 7, 16, 6),
    )

    assert result.inserted_tasks > 0
    assert await store.get_task(expected) is not None
    assert summaries.calls == []


async def test_prepare_backfills_rotated_host_history_from_discovery_start(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path)
    coordinator = ActivityRecoveryCoordinator(
        client=DiscoveryClient(
            data_start=local(2026, 7, 1),
            data_end=local(2026, 7, 16),
        ),
        repository=store,
        summaries=NoopSummaries(),
    )
    expected = ActivityWindowPlanner().task_id(
        SummaryTaskType.STAGE_6H,
        window_start=local(2026, 7, 1),
        window_end=local(2026, 7, 1, 6),
    )

    await coordinator.prepare(now=local(2026, 7, 16, 7))

    assert await store.get_task(expected) is not None


async def test_prepare_discovers_new_boundary_on_later_tick(tmp_path: Path) -> None:
    store = await repository(tmp_path)
    coordinator = ActivityRecoveryCoordinator(
        client=DiscoveryClient(
            data_start=local(2026, 7, 15),
            data_end=local(2026, 7, 16, 5),
        ),
        repository=store,
        summaries=NoopSummaries(),
    )
    expected = ActivityWindowPlanner().task_id(
        SummaryTaskType.STAGE_6H,
        window_start=local(2026, 7, 16),
        window_end=local(2026, 7, 16, 6),
    )

    await coordinator.prepare(now=local(2026, 7, 16, 5, 59))
    assert await store.get_task(expected) is None
    later = await coordinator.prepare(now=local(2026, 7, 16, 7))

    assert await store.get_task(expected) is not None
    assert later.inserted_tasks >= 1


async def test_prepare_uses_startup_full_audit_then_bounded_incremental_enumeration(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    store = RecordingRepository(database)
    planner = RecordingPlanner()
    data_start = local(2024, 1, 1)
    first = local(2026, 7, 16, 7)
    coordinator = ActivityRecoveryCoordinator(
        client=DiscoveryClient(
            data_start=data_start,
            data_end=first,
        ),
        repository=store,
        summaries=NoopSummaries(),
        planner=planner,
    )

    await coordinator.prepare(now=first)
    immediate_tick = first + timedelta(seconds=30)
    await coordinator.prepare(now=immediate_tick)
    await coordinator.prepare(now=first + timedelta(hours=6))

    assert planner.data_starts == [
        data_start,
        immediate_tick - timedelta(days=35),
        data_start,
    ]
    assert store.task_id_candidates == [set(), set(), set()]


async def test_startup_prepare_recovers_even_unexpired_running_lease(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path)
    now = local(2026, 7, 16, 7)
    task = ActivityWindowPlanner().window(
        SummaryTaskType.STAGE_6H,
        window_start=local(2026, 7, 16),
        window_end=local(2026, 7, 16, 6),
        created_at=now,
    )
    await store.ensure_tasks([task])
    rules = category_rule_version([])
    await store.save_category_rule_version(rules, now=now)
    claimed = await store.claim_task(
        task.id,
        lease_owner="dead-process",
        now=now,
        category_rule_version=rules.id,
        lease_duration=timedelta(hours=1),
    )
    assert claimed is not None
    coordinator = ActivityRecoveryCoordinator(
        client=DiscoveryClient(
            data_start=local(2026, 7, 15),
            data_end=now,
        ),
        repository=store,
        summaries=NoopSummaries(),
    )

    result = await coordinator.prepare(now=now + timedelta(minutes=1))
    recovered = await store.get_task(task.id)

    assert result.recovered_leases == 1
    assert recovered is not None
    assert recovered.status is SummaryTaskStatus.NEEDS_RETRY


async def test_startup_prepare_requeues_failed_task_once_for_compensation(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path)
    now = local(2026, 7, 16, 7)
    task = ActivityWindowPlanner().window(
        SummaryTaskType.STAGE_6H,
        window_start=local(2026, 7, 16),
        window_end=local(2026, 7, 16, 6),
        created_at=now,
    )
    await store.ensure_tasks([task])
    rules = category_rule_version([])
    await store.save_category_rule_version(rules, now=now)
    claimed = await store.claim_task(
        task.id,
        lease_owner="worker",
        now=now,
        category_rule_version=rules.id,
    )
    assert claimed is not None
    failed = await store.fail_attempt(
        task_id=task.id,
        attempt_id=claimed[1].id,
        error_code="old_permanent_failure",
        now=now,
        retryable=False,
    )
    assert failed.status is SummaryTaskStatus.FAILED
    coordinator = ActivityRecoveryCoordinator(
        client=DiscoveryClient(
            data_start=local(2026, 7, 15),
            data_end=now,
        ),
        repository=store,
        summaries=NoopSummaries(),
    )

    result = await coordinator.prepare(now=now + timedelta(minutes=1))
    requeued = await store.get_task(task.id)

    assert requeued is not None
    assert requeued.status is SummaryTaskStatus.NEEDS_RETRY
    assert task.id in result.due_task_ids


@pytest.mark.parametrize(
    "error_code",
    ("activity_model_output_rejected", "activity_model_invalid_response"),
)
async def test_startup_does_not_requeue_model_output_failures_without_user_request(
    tmp_path: Path,
    error_code: str,
) -> None:
    store = await repository(tmp_path)
    now = local(2026, 7, 16, 7)
    task = ActivityWindowPlanner().window(
        SummaryTaskType.STAGE_6H,
        window_start=local(2026, 7, 16),
        window_end=local(2026, 7, 16, 6),
        created_at=now,
    )
    await store.ensure_tasks([task])
    rules = category_rule_version([])
    await store.save_category_rule_version(rules, now=now)
    claimed = await store.claim_task(
        task.id,
        lease_owner="worker",
        now=now,
        category_rule_version=rules.id,
    )
    assert claimed is not None
    await store.fail_attempt(
        task_id=task.id,
        attempt_id=claimed[1].id,
        error_code=error_code,
        now=now,
        retryable=False,
    )
    coordinator = ActivityRecoveryCoordinator(
        client=DiscoveryClient(
            data_start=local(2026, 7, 15),
            data_end=now,
        ),
        repository=store,
        summaries=NoopSummaries(),
    )

    result = await coordinator.prepare(now=now + timedelta(minutes=1))
    current = await store.get_task(task.id)

    assert current is not None
    assert current.status is SummaryTaskStatus.FAILED
    assert task.id not in result.due_task_ids


async def test_reconcile_uses_a_fresh_clock_for_each_long_running_task() -> None:
    batch_now = datetime(2026, 7, 16, 0, tzinfo=UTC)
    execution_times = iter(
        (
            batch_now + timedelta(minutes=11),
            batch_now + timedelta(minutes=22),
        )
    )
    calls: list[datetime] = []
    planner = ActivityWindowPlanner()

    class RecordingSummaries:
        async def execute_task(self, task_id, *, now, lease_owner):
            assert lease_owner
            calls.append(now)
            task = planner.window(
                SummaryTaskType.STAGE_6H,
                window_start=batch_now - timedelta(hours=6),
                window_end=batch_now,
                created_at=now,
            )
            return task.model_copy(
                update={
                    "id": task_id,
                    "status": SummaryTaskStatus.COMPLETED,
                    "updated_at": now,
                }
            )

    source_state = ActivitySourceState(
        health=ActivitySourceHealth.AVAILABLE,
        checked_at=batch_now,
    )

    class PreparedCoordinator(ActivityRecoveryCoordinator):
        async def prepare(self, *, now):
            return ActivityReconciliationResult(
                source_state=source_state.model_copy(update={"checked_at": now}),
                due_task_ids=("first", "second"),
            )

    coordinator = PreparedCoordinator(
        client=object(),
        repository=object(),
        summaries=RecordingSummaries(),
        clock=lambda: next(execution_times),
    )

    result = await coordinator.reconcile(now=batch_now)

    assert calls == [
        batch_now + timedelta(minutes=11),
        batch_now + timedelta(minutes=22),
    ]
    assert result.processed_task_ids == ("first", "second")


@pytest.mark.parametrize(
    "shared_error_code",
    [
        "activity_model_credential_unavailable",
        "activity_model_provider_authentication_failed",
        "activity_model_route_version_mismatch",
    ],
)
async def test_reconcile_pauses_the_batch_behind_one_shared_model_failure(
    shared_error_code: str,
) -> None:
    batch_now = datetime(2026, 7, 16, 0, tzinfo=UTC)
    calls: list[tuple[str, datetime]] = []
    planner = ActivityWindowPlanner()

    class RecoveringSummaries:
        first_failed = False

        async def execute_task(self, task_id, *, now, lease_owner):
            assert lease_owner
            calls.append((task_id, now))
            task = planner.window(
                SummaryTaskType.STAGE_6H,
                window_start=batch_now - timedelta(hours=6),
                window_end=batch_now,
                created_at=now,
            )
            if task_id == "first" and not self.first_failed:
                self.first_failed = True
                return task.model_copy(
                    update={
                        "id": task_id,
                        "status": SummaryTaskStatus.NEEDS_RETRY,
                        "next_retry_at": now + timedelta(minutes=5),
                        "error_code": shared_error_code,
                        "updated_at": now,
                    }
                )
            return task.model_copy(
                update={
                    "id": task_id,
                    "status": SummaryTaskStatus.COMPLETED,
                    "updated_at": now,
                }
            )

    source_state = ActivitySourceState(
        health=ActivitySourceHealth.AVAILABLE,
        checked_at=batch_now,
    )

    class PreparedCoordinator(ActivityRecoveryCoordinator):
        async def prepare(self, *, now):
            return ActivityReconciliationResult(
                source_state=source_state.model_copy(update={"checked_at": now}),
                due_task_ids=("first", "second"),
            )

    coordinator = PreparedCoordinator(
        client=object(),
        repository=object(),
        summaries=RecoveringSummaries(),
        clock=lambda: batch_now,
    )

    failed = await coordinator.reconcile(now=batch_now)
    held = await coordinator.reconcile(now=batch_now + timedelta(minutes=1))
    recovered = await coordinator.reconcile(now=batch_now + timedelta(minutes=5))

    assert calls == [
        ("first", batch_now),
        ("first", batch_now + timedelta(minutes=5)),
        ("second", batch_now + timedelta(minutes=5)),
    ]
    assert failed.failed_task_ids == ("first",)
    assert held.processed_task_ids == ()
    assert held.failed_task_ids == ()
    assert recovered.processed_task_ids == ("first", "second")
