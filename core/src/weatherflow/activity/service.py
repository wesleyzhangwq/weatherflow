from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Protocol

from weatherflow.activity.models import (
    ActivityHeartbeat,
    ActivityInterval,
    ActivityPreferences,
    ActivityRankItem,
    ActivitySource,
    ActivitySummary,
    IdleState,
    require_aware,
)
from weatherflow.activity.repository import ActivityRepository
from weatherflow.activity.sanitizer import ActivitySanitizer


class ActivityCollectionDisabledError(PermissionError):
    pass


class ActivityInferenceEvidenceStore(Protocol):
    async def delete_for_event_ids(self, event_ids: tuple[str, ...]) -> int: ...


class ActivityService:
    def __init__(
        self,
        *,
        repository: ActivityRepository,
        sanitizer: ActivitySanitizer | None = None,
        inference_evidence: ActivityInferenceEvidenceStore | None = None,
        delete_projection: Callable[[tuple[str, ...]], Awaitable[int]] | None = None,
    ) -> None:
        self.repository = repository
        self.sanitizer = sanitizer or ActivitySanitizer()
        self.inference_evidence = inference_evidence
        self.delete_projection = delete_projection
        self._retention_checked_at: datetime | None = None

    async def preferences(self) -> ActivityPreferences:
        return await self.repository.get_preferences()

    async def update_preferences(
        self,
        preferences: ActivityPreferences,
        *,
        expected_version: int,
    ) -> ActivityPreferences:
        return await self.repository.save_preferences(
            preferences,
            expected_version=expected_version,
        )

    async def ingest(self, heartbeat: ActivityHeartbeat) -> ActivityInterval:
        preferences = await self.repository.get_preferences()
        if not preferences.collection_enabled:
            raise ActivityCollectionDisabledError("activity collection is disabled")
        if heartbeat.source is ActivitySource.MACOS_WINDOW and not preferences.macos_enabled:
            raise ActivityCollectionDisabledError("macOS collection is disabled")
        if heartbeat.source is ActivitySource.BROWSER_TAB:
            if not preferences.browser_enabled:
                raise ActivityCollectionDisabledError("browser collection is disabled")
            if heartbeat.incognito and not preferences.incognito_enabled:
                raise ActivityCollectionDisabledError("incognito collection is disabled")
        sanitized, _redaction_count = self.sanitizer.sanitize_heartbeat(heartbeat)
        return await self.repository.record_heartbeat(sanitized)

    async def apply_retention(self, *, now: datetime) -> int:
        observed = require_aware(now)
        preferences = await self.repository.get_preferences()
        if preferences.retention_days is None:
            return 0
        cutoff = observed - timedelta(days=preferences.retention_days)
        event_ids = await self.repository.event_ids_before(cutoff)
        if event_ids and self.inference_evidence is not None:
            await self.inference_evidence.delete_for_event_ids(event_ids)
        if event_ids and self.delete_projection is not None:
            await self.delete_projection(event_ids)
        return await self.repository.delete_before(cutoff)

    async def maybe_apply_retention(self, *, now: datetime) -> int:
        observed = require_aware(now)
        if (
            self._retention_checked_at is not None
            and observed - self._retention_checked_at < timedelta(hours=1)
        ):
            return 0
        self._retention_checked_at = observed
        return await self.apply_retention(now=observed)

    async def delete_range(self, *, start: datetime, end: datetime) -> int:
        events = await self.repository.list_events_for_inference(start=start, end=end)
        event_ids = tuple(event.id for event in events)
        if event_ids and self.inference_evidence is not None:
            await self.inference_evidence.delete_for_event_ids(event_ids)
        if event_ids and self.delete_projection is not None:
            await self.delete_projection(event_ids)
        return await self.repository.delete_range(start=start, end=end)

    async def summary(self, *, start: datetime, end: datetime) -> ActivitySummary:
        window_start = require_aware(start)
        window_end = require_aware(end)
        events = await self.repository.list_events_for_inference(
            start=window_start,
            end=window_end,
        )

        screen_seconds = 0.0
        browser_seconds = 0.0
        idle_seconds = 0.0
        app_seconds: dict[str, float] = defaultdict(float)
        domain_seconds: dict[str, float] = defaultdict(float)
        category_seconds: dict[str, float] = defaultdict(float)

        for event in events:
            duration = self._overlap_seconds(event, window_start, window_end)
            if duration <= 0:
                continue
            if event.source is ActivitySource.MACOS_WINDOW and (
                event.idle_state is IdleState.IDLE or event.focused is False
            ):
                idle_seconds += duration
                continue
            if event.idle_state is IdleState.IDLE or event.focused is False:
                continue
            if event.source is ActivitySource.MACOS_WINDOW:
                screen_seconds += duration
                if event.app_name:
                    app_seconds[event.app_name] += duration
                if event.category:
                    category_seconds[event.category] += duration
            elif event.source is ActivitySource.BROWSER_TAB:
                browser_seconds += duration
                if event.domain:
                    domain_seconds[event.domain] += duration

        return ActivitySummary(
            window_start=window_start,
            window_end=window_end,
            screen_seconds=screen_seconds,
            browser_seconds=browser_seconds,
            idle_seconds=idle_seconds,
            current_streak_seconds=self._current_streak(
                events,
                start=window_start,
                end=window_end,
            ),
            app_switch_count=self._count_switches(events, "bundle_id"),
            tab_switch_count=self._count_switches(events, "browser_tab_id"),
            category_seconds=dict(category_seconds),
            top_apps=self._rank(app_seconds),
            top_domains=self._rank(domain_seconds),
        )

    @staticmethod
    def _current_streak(
        events: list[ActivityInterval],
        *,
        start: datetime,
        end: datetime,
    ) -> float:
        mac_events = sorted(
            (event for event in events if event.source is ActivitySource.MACOS_WINDOW),
            key=lambda event: (event.started_at, event.id),
        )
        if not mac_events:
            return 0.0
        latest = mac_events[-1]
        if (
            latest.idle_state is not IdleState.ACTIVE
            or latest.focused is False
            or (end - latest.ended_at).total_seconds() > 90
        ):
            return 0.0
        streak_start = max(start, latest.started_at)
        next_start = latest.started_at
        for event in reversed(mac_events[:-1]):
            gap = (next_start - event.ended_at).total_seconds()
            if event.idle_state is not IdleState.ACTIVE or event.focused is False or gap > 90:
                break
            streak_start = max(start, event.started_at)
            next_start = event.started_at
        return max(0.0, (end - streak_start).total_seconds())

    @staticmethod
    def _overlap_seconds(
        event: ActivityInterval,
        start: datetime,
        end: datetime,
    ) -> float:
        return max(
            0.0,
            (min(event.ended_at, end) - max(event.started_at, start)).total_seconds(),
        )

    @staticmethod
    def _count_switches(events: list[ActivityInterval], field: str) -> int:
        previous_by_source: dict[str, str] = {}
        switches = 0
        for event in events:
            identity = getattr(event, field)
            if not identity:
                continue
            previous = previous_by_source.get(event.source_instance)
            if previous is not None and previous != identity:
                switches += 1
            previous_by_source[event.source_instance] = identity
        return switches

    @staticmethod
    def _rank(values: dict[str, float]) -> tuple[ActivityRankItem, ...]:
        return tuple(
            ActivityRankItem(name=name, seconds=seconds)
            for name, seconds in sorted(
                values.items(),
                key=lambda item: (-item[1], item[0].casefold()),
            )
        )
