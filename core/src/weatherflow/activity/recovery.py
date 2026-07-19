from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from weatherflow.activity.activitywatch import ActivityWatchReadClient
from weatherflow.activity.models import (
    ActivityReconciliationResult,
    ActivitySourceHealth,
    ActivitySourceState,
    SummaryTaskStatus,
    require_aware,
)
from weatherflow.activity.repository import ActivityRepository
from weatherflow.activity.service import ActivitySummaryService
from weatherflow.activity.windows import ActivityWindowPlanner

_SHARED_MODEL_FAILURE_CODES = frozenset(
    {
        "activity_model_credential_unavailable",
        "activity_model_provider_authentication_failed",
        "activity_model_route_version_mismatch",
        # Keep the pre-split code bounded after upgrading an existing ledger.
        "activity_model_authentication_failed",
    }
)


class ActivityRecoveryCoordinator:
    """Enumerates theoretical windows and repairs derived work chronologically."""

    DEFAULT_INCREMENTAL_LOOKBACK = timedelta(days=35)
    DEFAULT_FULL_AUDIT_INTERVAL = timedelta(hours=6)

    def __init__(
        self,
        *,
        client: ActivityWatchReadClient,
        repository: ActivityRepository,
        summaries: ActivitySummaryService,
        planner: ActivityWindowPlanner | None = None,
        lease_owner: str | None = None,
        max_tasks_per_pass: int = 100,
        clock: Callable[[], datetime] | None = None,
        incremental_lookback: timedelta = DEFAULT_INCREMENTAL_LOOKBACK,
        full_audit_interval: timedelta = DEFAULT_FULL_AUDIT_INTERVAL,
    ) -> None:
        if max_tasks_per_pass < 1 or max_tasks_per_pass > 10_000:
            raise ValueError("max_tasks_per_pass must be between 1 and 10000")
        if incremental_lookback <= timedelta(0):
            raise ValueError("incremental_lookback must be positive")
        if full_audit_interval <= timedelta(0):
            raise ValueError("full_audit_interval must be positive")
        self.client = client
        self.repository = repository
        self.summaries = summaries
        self.planner = planner or ActivityWindowPlanner()
        self.lease_owner = lease_owner or f"activity-recovery:{uuid4()}"
        self.max_tasks_per_pass = max_tasks_per_pass
        self.clock = clock or (lambda: datetime.now(UTC))
        self.incremental_lookback = incremental_lookback
        self.full_audit_interval = full_audit_interval
        self._startup_recovery_complete = False
        self._last_full_audit_at: datetime | None = None
        self._model_retry_not_before: datetime | None = None

    async def prepare(self, *, now: datetime) -> ActivityReconciliationResult:
        observed = require_aware(now)
        previous = await self.repository.source_state()
        try:
            discovery = await self.client.discover()
        except Exception:
            degraded = ActivitySourceState(
                health=ActivitySourceHealth.DEGRADED,
                checked_at=observed,
                server_id=previous.server_id if previous else None,
                server_version=previous.server_version if previous else None,
                bucket_count=previous.bucket_count if previous else 0,
                data_start=previous.data_start if previous else None,
                data_end=previous.data_end if previous else None,
                category_rule_version=(previous.category_rule_version if previous else None),
                history_cutoff=previous.history_cutoff if previous else None,
                last_reconciled_at=(previous.last_reconciled_at if previous else None),
                error_code="activitywatch_unavailable",
            )
            degraded = await self.repository.save_source_state(degraded)
            return ActivityReconciliationResult(source_state=degraded)

        await self.repository.save_category_rule_version(
            discovery.category_rules,
            now=observed,
        )
        source_state = ActivitySourceState(
            health=ActivitySourceHealth.AVAILABLE,
            checked_at=observed,
            server_id=discovery.info.server_id,
            server_version=discovery.info.version,
            bucket_count=len(discovery.buckets),
            data_start=discovery.data_start,
            data_end=discovery.data_end,
            category_rule_version=discovery.category_rules.id,
            history_cutoff=previous.history_cutoff if previous else None,
            last_reconciled_at=previous.last_reconciled_at if previous else None,
        )
        source_state = await self.repository.save_source_state(source_state)
        startup_recovery = not self._startup_recovery_complete
        recovered = await self.repository.recover_expired_leases(
            now=observed,
            include_unexpired=startup_recovery,
        )
        if startup_recovery:
            await self.repository.requeue_failed_tasks(now=observed)
        self._startup_recovery_complete = True
        inserted_tasks = 0
        inserted_dependencies = 0
        full_audit = self._full_audit_due(now=observed)
        if discovery.data_start is not None:
            analysis_start = max(
                discovery.data_start,
                source_state.history_cutoff
                if source_state.history_cutoff is not None
                else discovery.data_start,
            )
            enumeration_start = (
                analysis_start
                if full_audit
                else max(analysis_start, observed - self.incremental_lookback)
            )
            theoretical = self.planner.expected_windows(
                data_start=enumeration_start,
                now=observed,
            )
            if source_state.history_cutoff is not None:
                theoretical = [
                    task for task in theoretical if task.window_start >= source_state.history_cutoff
                ]
            inserted_tasks = await self.repository.ensure_tasks(theoretical)
            existing_ids = await self.repository.task_ids(
                candidate_ids={task.id for task in theoretical}
            )
            dependencies = [
                dependency
                for dependency in self.planner.dependencies(theoretical)
                if dependency.parent_task_id in existing_ids
                and dependency.child_task_id in existing_ids
            ]
            inserted_dependencies = await self.repository.ensure_dependencies(dependencies)
        if full_audit:
            self._last_full_audit_at = observed
        if (
            startup_recovery
            or previous is None
            or (previous.category_rule_version != discovery.category_rules.id)
        ):
            await self.repository.mark_legacy_rule_revisions(
                current_category_rule_version=discovery.category_rules.id
            )
        due = await self.repository.list_due_tasks(
            now=observed,
            category_rule_version=discovery.category_rules.id,
            limit=self.max_tasks_per_pass,
        )
        reconciled_state = source_state.model_copy(update={"last_reconciled_at": observed})
        reconciled_state = await self.repository.save_source_state(reconciled_state)
        return ActivityReconciliationResult(
            source_state=reconciled_state,
            inserted_tasks=inserted_tasks,
            inserted_dependencies=inserted_dependencies,
            recovered_leases=len(recovered),
            due_task_ids=tuple(task.id for task in due),
        )

    def _full_audit_due(self, *, now: datetime) -> bool:
        if not self._startup_recovery_complete or self._last_full_audit_at is None:
            return True
        return now >= self._last_full_audit_at + self.full_audit_interval

    async def reconcile(self, *, now: datetime) -> ActivityReconciliationResult:
        observed = require_aware(now)
        prepared = await self.prepare(now=observed)
        if prepared.source_state.health is not ActivitySourceHealth.AVAILABLE:
            return prepared
        if self._model_retry_not_before is not None:
            if observed < self._model_retry_not_before:
                return prepared
            self._model_retry_not_before = None
        processed: list[str] = []
        failed: list[str] = []
        for task_id in prepared.due_task_ids:
            execution_now = max(observed, require_aware(self.clock()))
            result = await self.summaries.execute_task(
                task_id,
                now=execution_now,
                lease_owner=self.lease_owner,
            )
            if result.status is SummaryTaskStatus.COMPLETED:
                processed.append(result.id)
            elif result.status in {
                SummaryTaskStatus.FAILED,
                SummaryTaskStatus.NEEDS_RETRY,
            }:
                failed.append(result.id)
                if result.error_code in _SHARED_MODEL_FAILURE_CODES:
                    self._model_retry_not_before = (
                        result.next_retry_at
                        if result.next_retry_at is not None
                        else execution_now + timedelta(minutes=5)
                    )
                    break
        return prepared.model_copy(
            update={
                "processed_task_ids": tuple(processed),
                "failed_task_ids": tuple(failed),
            }
        )


class ActivitySummaryScheduler:
    """Continuously discovers new boundaries and reconciles missed work."""

    def __init__(
        self,
        *,
        coordinator: ActivityRecoveryCoordinator,
        interval_seconds: float = 30.0,
        max_offline_backoff_seconds: float = 300.0,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if max_offline_backoff_seconds < interval_seconds:
            raise ValueError("offline backoff must not be shorter than the interval")
        self.coordinator = coordinator
        self.interval_seconds = interval_seconds
        self.max_offline_backoff_seconds = max_offline_backoff_seconds
        self.now = now or (lambda: datetime.now(UTC))
        self.sleep = sleep
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def tick(self, *, now: datetime | None = None) -> ActivityReconciliationResult:
        return await self.coordinator.reconcile(now=now or self.now())

    async def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(
            self._run(),
            name="weatherflow-activity-summary-recovery",
        )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _run(self) -> None:
        delay = self.interval_seconds
        while True:
            try:
                result = await self.tick()
                if result.source_state.health is ActivitySourceHealth.AVAILABLE:
                    delay = self.interval_seconds
                else:
                    delay = min(
                        self.max_offline_backoff_seconds,
                        max(self.interval_seconds, delay * 2),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                delay = min(
                    self.max_offline_backoff_seconds,
                    max(self.interval_seconds, delay * 2),
                )
            await self.sleep(delay)
