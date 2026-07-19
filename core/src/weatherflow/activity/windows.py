from __future__ import annotations

import hashlib
from bisect import bisect_left
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from weatherflow.activity.models import (
    ACTIVITY_TIMEZONE,
    BOUNDARY_POLICY_VERSION,
    ActivitySummaryDependency,
    ActivitySummaryTask,
    SummaryFinality,
    SummaryTaskType,
    require_aware,
)

PROVISIONAL_GRACE = timedelta(minutes=15)
FINAL_GRACE = timedelta(minutes=60)
BIWEEKLY_ANCHOR = date(1970, 1, 5)


class ActivityWindowPlanner:
    timezone = ZoneInfo(ACTIVITY_TIMEZONE)
    boundary_policy_version = BOUNDARY_POLICY_VERSION

    def window(
        self,
        task_type: SummaryTaskType,
        *,
        window_start: datetime,
        window_end: datetime,
        created_at: datetime | None = None,
    ) -> ActivitySummaryTask:
        start = require_aware(window_start)
        end = require_aware(window_end)
        if end <= start:
            raise ValueError("window_end must be after window_start")
        observed = require_aware(created_at or end)
        return ActivitySummaryTask(
            id=self.task_id(task_type, window_start=start, window_end=end),
            task_type=task_type,
            window_start=start,
            window_end=end,
            not_before=end + PROVISIONAL_GRACE,
            created_at=observed,
            updated_at=observed,
        )

    def task_id(
        self,
        task_type: SummaryTaskType,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> str:
        start = require_aware(window_start)
        end = require_aware(window_end)
        identity = "|".join(
            (
                task_type.value,
                ACTIVITY_TIMEZONE,
                self.boundary_policy_version,
                start.isoformat(),
                end.isoformat(),
            )
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def finality(
        self,
        task: ActivitySummaryTask,
        *,
        now: datetime,
    ) -> SummaryFinality | None:
        elapsed = require_aware(now) - task.window_end
        if elapsed < PROVISIONAL_GRACE:
            return None
        if elapsed < FINAL_GRACE:
            return SummaryFinality.PROVISIONAL
        return SummaryFinality.FINAL

    def expected_windows(
        self,
        *,
        data_start: datetime,
        now: datetime,
        data_end: datetime | None = None,
    ) -> list[ActivitySummaryTask]:
        start = require_aware(data_start)
        observed = require_aware(now)
        available_end = require_aware(data_end) if data_end is not None else None
        if available_end is not None and available_end < start:
            raise ValueError("data_end must not be before data_start")
        # The latest event is coverage metadata, not a scheduling cursor.
        # Sleep, AFK, and otherwise empty periods still have theoretical windows.
        horizon = observed
        if horizon <= start:
            return []

        tasks: list[ActivitySummaryTask] = []
        for task_type in SummaryTaskType:
            for local_start, local_end in self._local_windows(
                task_type,
                data_start=start.astimezone(self.timezone),
                horizon=horizon.astimezone(self.timezone),
            ):
                window_start = local_start.astimezone(UTC)
                window_end = local_end.astimezone(UTC)
                if window_end <= start or window_start >= horizon or window_end > observed:
                    continue
                tasks.append(
                    self.window(
                        task_type,
                        window_start=window_start,
                        window_end=window_end,
                        created_at=observed,
                    )
                )
        tasks.sort(
            key=lambda task: (
                task.window_end,
                self.granularity_rank(task.task_type),
                task.window_start,
                task.id,
            )
        )
        return tasks

    def dependencies(
        self,
        tasks: list[ActivitySummaryTask],
    ) -> list[ActivitySummaryDependency]:
        dependencies: set[tuple[str, str]] = set()
        by_type: dict[SummaryTaskType, list[ActivitySummaryTask]] = {
            task_type: [] for task_type in SummaryTaskType
        }
        for task in tasks:
            by_type[task.task_type].append(task)
        starts: dict[SummaryTaskType, list[datetime]] = {}
        for task_type, typed_tasks in by_type.items():
            typed_tasks.sort(key=lambda task: (task.window_start, task.window_end, task.id))
            starts[task_type] = [task.window_start for task in typed_tasks]

        for parent in tasks:
            parent_rank = self.granularity_rank(parent.task_type)
            if parent_rank == 0:
                continue
            for child_type in SummaryTaskType:
                if self.granularity_rank(child_type) >= parent_rank:
                    continue
                candidates = by_type[child_type]
                index = bisect_left(starts[child_type], parent.window_start)
                while index < len(candidates):
                    child = candidates[index]
                    if child.window_start >= parent.window_end:
                        break
                    if child.window_end <= parent.window_end:
                        dependencies.add((parent.id, child.id))
                    index += 1
        return [
            ActivitySummaryDependency(parent_task_id=parent, child_task_id=child)
            for parent, child in sorted(dependencies)
        ]

    @staticmethod
    def granularity_rank(task_type: SummaryTaskType) -> int:
        return {
            SummaryTaskType.STAGE_6H: 0,
            SummaryTaskType.DAILY_24H: 1,
            SummaryTaskType.WEEKLY: 2,
            SummaryTaskType.BIWEEKLY: 3,
            SummaryTaskType.MONTHLY: 4,
        }[task_type]

    def _local_windows(
        self,
        task_type: SummaryTaskType,
        *,
        data_start: datetime,
        horizon: datetime,
    ):
        current = self._containing_start(task_type, data_start)
        produced = 0
        while current < horizon:
            end = self._next_boundary(task_type, current)
            yield current, end
            current = end
            produced += 1
            if produced > 100_000:
                raise ValueError("ActivityWatch data range exceeds the planner bound")

    def _containing_start(
        self,
        task_type: SummaryTaskType,
        value: datetime,
    ) -> datetime:
        local = value.astimezone(self.timezone)
        if task_type is SummaryTaskType.STAGE_6H:
            return local.replace(
                hour=(local.hour // 6) * 6,
                minute=0,
                second=0,
                microsecond=0,
            )
        if task_type is SummaryTaskType.DAILY_24H:
            boundary = local.replace(hour=6, minute=0, second=0, microsecond=0)
            return boundary if local >= boundary else boundary - timedelta(days=1)
        if task_type is SummaryTaskType.WEEKLY:
            monday = local.date() - timedelta(days=local.weekday())
            return datetime.combine(monday, time.min, tzinfo=self.timezone)
        if task_type is SummaryTaskType.BIWEEKLY:
            days = (local.date() - BIWEEKLY_ANCHOR).days
            anchor = BIWEEKLY_ANCHOR + timedelta(days=(days // 14) * 14)
            return datetime.combine(anchor, time.min, tzinfo=self.timezone)
        if task_type is SummaryTaskType.MONTHLY:
            return datetime(local.year, local.month, 1, tzinfo=self.timezone)
        raise ValueError(task_type)

    def _next_boundary(
        self,
        task_type: SummaryTaskType,
        current: datetime,
    ) -> datetime:
        if task_type is SummaryTaskType.STAGE_6H:
            return current + timedelta(hours=6)
        if task_type is SummaryTaskType.DAILY_24H:
            return current + timedelta(days=1)
        if task_type is SummaryTaskType.WEEKLY:
            return current + timedelta(days=7)
        if task_type is SummaryTaskType.BIWEEKLY:
            return current + timedelta(days=14)
        if task_type is SummaryTaskType.MONTHLY:
            if current.month == 12:
                return datetime(current.year + 1, 1, 1, tzinfo=self.timezone)
            return datetime(current.year, current.month + 1, 1, tzinfo=self.timezone)
        raise ValueError(task_type)
