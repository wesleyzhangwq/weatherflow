from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from weatherflow.activity.activitywatch import ActivityWatchReadClient
from weatherflow.activity.categories import CategoryMatcher, category_rule_version
from weatherflow.activity.context import ActivityContextPack, ActivityContextPackBuilder
from weatherflow.activity.models import (
    ActivityCoverageStatus,
    ActivityEvidenceRef,
    ActivityRangeResult,
    ActivityRankItem,
    ActivitySourceHealth,
    ActivityStatistics,
    ActivitySummaryRevision,
    ActivitySummaryTask,
    ActivityTrendPoint,
    ActivityWatchBucket,
    ActivityWatchEvent,
    AfkState,
    CategoryRuleVersion,
    CurrentActivityState,
    ObservedActivityFact,
    ObservedFactKind,
    SummaryTaskStatus,
    SummaryTaskType,
    canonical_digest,
    require_aware,
)
from weatherflow.activity.repository import ActivityRepository


class ActivityQueryLimitExceeded(RuntimeError):
    pass


class ActivityCategoryRulesChanged(RuntimeError):
    pass


@dataclass(frozen=True)
class ActivityWindowEvidence:
    statistics: ActivityStatistics
    evidence_refs: tuple[ActivityEvidenceRef, ...]
    model_facts: tuple[ObservedActivityFact, ...]
    category_rules: CategoryRuleVersion
    context_pack: ActivityContextPack | None = None


@dataclass(frozen=True)
class ActivityDashboardWindow:
    statistics: ActivityStatistics
    timeline: ActivityRangeResult


@dataclass(frozen=True)
class ActivitySourceSegment:
    start: datetime
    end: datetime
    window_bucket: ActivityWatchBucket
    afk_bucket: ActivityWatchBucket | None
    web_buckets: tuple[ActivityWatchBucket, ...]

    @property
    def buckets(self) -> tuple[ActivityWatchBucket, ...]:
        return (
            self.window_bucket,
            *((self.afk_bucket,) if self.afk_bucket is not None else ()),
            *self.web_buckets,
        )


@dataclass(frozen=True)
class ActivityAfkSegment:
    start: datetime
    end: datetime
    bucket: ActivityWatchBucket


class ActivitySemanticQueryService:
    """Fixed-purpose, bounded semantic reads over ActivityWatch."""

    max_ui_range = timedelta(days=31)
    max_statistics_range = timedelta(days=370)
    max_ui_events = 2_000
    max_events_per_bucket = 10_000
    max_total_events = 250_000
    max_slice_depth = 32
    max_model_evidence = 120
    max_persisted_evidence = 120
    max_dashboard_web_buckets = 16
    current_fact_freshness = timedelta(minutes=2)
    current_query_window = timedelta(minutes=5)
    max_current_web_buckets = 16

    def __init__(
        self,
        *,
        client: ActivityWatchReadClient,
        repository: ActivityRepository,
    ) -> None:
        self.client = client
        self.repository = repository
        self.context_builder = ActivityContextPackBuilder()

    async def current_state(self, *, now: datetime) -> CurrentActivityState:
        observed = require_aware(now)
        current_start = observed - self.current_query_window
        try:
            _info, segments = await self._selected_segments(
                start=current_start,
                end=observed + timedelta(seconds=1),
                max_web_buckets=self.max_current_web_buckets,
            )
            facts = await self._fetch_segment_facts(
                segments,
                start=current_start,
                end=observed + timedelta(seconds=1),
                per_bucket_limit=20,
            )
            if not any(fact.kind is ObservedFactKind.AFK for fact in facts):
                facts.extend(
                    await self._fetch_afk_facts(
                        start=current_start,
                        end=observed + timedelta(seconds=1),
                        per_bucket_limit=20,
                    )
                )
                facts.sort(
                    key=lambda fact: (
                        fact.timestamp,
                        fact.bucket_id,
                        fact.event_id,
                    )
                )
        except Exception:
            return CurrentActivityState(
                observed=None,
                afk_state=AfkState.UNKNOWN,
                observed_at=observed,
                source_health=ActivitySourceHealth.DEGRADED,
            )
        window = max(
            (fact for fact in facts if fact.kind is ObservedFactKind.WINDOW),
            key=lambda fact: (fact.timestamp, fact.event_id),
            default=None,
        )
        web = max(
            (fact for fact in facts if fact.kind is ObservedFactKind.WEB),
            key=lambda fact: (fact.timestamp, fact.event_id),
            default=None,
        )
        afk = max(
            (fact for fact in facts if fact.kind is ObservedFactKind.AFK),
            key=lambda fact: (fact.timestamp, fact.event_id),
            default=None,
        )
        if (
            window is not None
            and observed - min(observed, window.ended_at) > self.current_fact_freshness
        ):
            window = None
        if afk is not None and observed - min(observed, afk.ended_at) > self.current_fact_freshness:
            afk = None
        if web is not None and observed - min(observed, web.ended_at) > self.current_fact_freshness:
            web = None
        return CurrentActivityState(
            observed=window,
            web_context=web,
            afk_state=afk.afk_state if afk is not None else AfkState.UNKNOWN,
            observed_at=observed,
            source_health=ActivitySourceHealth.AVAILABLE,
        )

    async def recent_activity(
        self,
        *,
        now: datetime,
        minutes: int = 60,
        limit: int = 200,
    ) -> ActivityRangeResult:
        if minutes < 1 or minutes > 7 * 24 * 60:
            raise ValueError("minutes must be between 1 and 10080")
        observed = require_aware(now)
        return await self.query_range(
            start=observed - timedelta(minutes=minutes),
            end=observed,
            limit=limit,
            latest_first=True,
        )

    async def query_range(
        self,
        *,
        start: datetime,
        end: datetime,
        limit: int = 500,
        app_name: str | None = None,
        category: str | None = None,
        domain: str | None = None,
        latest_first: bool = False,
    ) -> ActivityRangeResult:
        window_start, window_end = self._bounded_window(
            start,
            end,
            maximum=self.max_ui_range,
        )
        if limit < 1 or limit > self.max_ui_events:
            raise ValueError(f"limit must be between 1 and {self.max_ui_events}")
        _info, segments = await self._selected_segments(
            start=window_start,
            end=window_end,
        )
        facts = await self._fetch_segment_facts(
            segments,
            start=window_start,
            end=window_end,
            per_bucket_limit=self.max_events_per_bucket,
            require_complete=True,
        )
        if app_name is not None:
            facts = [fact for fact in facts if fact.application == app_name]
        if domain is not None:
            facts = [fact for fact in facts if fact.domain == domain]
        if category is not None:
            matcher = CategoryMatcher(await self.client.classes())
            facts = [fact for fact in facts if matcher.match(fact) == category]
        if latest_first:
            facts.sort(key=self._timeline_order, reverse=True)
        else:
            facts.sort(key=lambda fact: (fact.timestamp, fact.bucket_id, fact.event_id))
        truncated = len(facts) > limit
        return ActivityRangeResult(
            window_start=window_start,
            window_end=window_end,
            facts=tuple(facts[:limit]),
            truncated=truncated,
        )

    async def timeline(
        self,
        *,
        start: datetime,
        end: datetime,
        limit: int = 500,
    ) -> ActivityRangeResult:
        return await self.query_range(
            start=start,
            end=end,
            limit=limit,
            latest_first=True,
        )

    async def dashboard_window(
        self,
        *,
        start: datetime,
        end: datetime,
        limit: int = 500,
    ) -> ActivityDashboardWindow:
        """Read one bounded Watch dashboard window exactly once.

        Statistics and timeline share the same source snapshot so the desktop
        does not issue two complete ActivityWatch scans for every refresh.
        """

        window_start, window_end = self._bounded_window(
            start,
            end,
            maximum=self.max_ui_range,
        )
        if limit < 1 or limit > self.max_ui_events:
            raise ValueError(f"limit must be between 1 and {self.max_ui_events}")
        rules = category_rule_version(await self.client.classes())
        _info, segments = await self._selected_segments(
            start=window_start,
            end=window_end,
            max_web_buckets=self.max_dashboard_web_buckets,
        )
        facts = await self._fetch_segment_facts(
            segments,
            start=window_start,
            end=window_end,
            per_bucket_limit=self.max_events_per_bucket,
            require_complete=True,
        )
        category_seconds: dict[str, float] = defaultdict(float)
        for segment in segments:
            if segment.afk_bucket is None:
                continue
            segment_usage = await self._server_category_usage(
                start=max(window_start, segment.start),
                end=min(window_end, segment.end),
                category_rules=rules,
                window_bucket_id=segment.window_bucket.id,
                afk_bucket_id=segment.afk_bucket.id,
            )
            for name, seconds in segment_usage.items():
                category_seconds[name] += seconds
        rules_after = category_rule_version(await self.client.classes())
        if rules_after.id != rules.id:
            raise ActivityCategoryRulesChanged(
                "ActivityWatch Category rules changed during the dashboard read"
            )
        statistics = self._statistics(
            facts,
            start=window_start,
            end=window_end,
            category_rules=rules,
            category_seconds=dict(category_seconds),
            source_bucket_ids=self._segment_bucket_ids(segments),
        )
        facts.sort(key=self._timeline_order, reverse=True)
        return ActivityDashboardWindow(
            statistics=statistics,
            timeline=ActivityRangeResult(
                window_start=window_start,
                window_end=window_end,
                facts=tuple(facts[:limit]),
                truncated=len(facts) > limit,
            ),
        )

    @staticmethod
    def _timeline_order(fact: ObservedActivityFact) -> tuple[datetime, datetime, str, str]:
        return (
            fact.ended_at,
            fact.timestamp,
            fact.bucket_id,
            fact.event_id,
        )

    async def collect_window(
        self,
        *,
        start: datetime,
        end: datetime,
        server_id: str | None = None,
        category_rules: CategoryRuleVersion | None = None,
    ) -> ActivityWindowEvidence:
        window_start, window_end = self._bounded_window(
            start,
            end,
            maximum=self.max_statistics_range,
        )
        rules = category_rules or category_rule_version(await self.client.classes())
        info, segments = await self._selected_segments(
            start=window_start,
            end=window_end,
        )
        facts = await self._fetch_segment_facts(
            segments,
            start=window_start,
            end=window_end,
            per_bucket_limit=self.max_events_per_bucket,
            require_complete=True,
        )
        category_seconds: dict[str, float] = defaultdict(float)
        for segment in segments:
            if segment.afk_bucket is None:
                continue
            segment_usage = await self._server_category_usage(
                start=max(window_start, segment.start),
                end=min(window_end, segment.end),
                category_rules=rules,
                window_bucket_id=segment.window_bucket.id,
                afk_bucket_id=segment.afk_bucket.id,
            )
            for name, seconds in segment_usage.items():
                category_seconds[name] += seconds
        rules_after = category_rule_version(await self.client.classes())
        if rules_after.id != rules.id:
            raise ActivityCategoryRulesChanged(
                "ActivityWatch Category rules changed during the source-window read"
            )
        server = server_id or info.server_id
        sampled_facts = self._sample_facts(
            facts,
            min(self.max_model_evidence, self.max_persisted_evidence),
        )
        references = tuple(
            fact.evidence_ref(
                server_id=server,
                fields_used=self._fields_used(fact),
            )
            for fact in sampled_facts
        )
        statistics = self._statistics(
            facts,
            start=window_start,
            end=window_end,
            category_rules=rules,
            category_seconds=dict(category_seconds),
            source_bucket_ids=self._segment_bucket_ids(segments),
        )
        context_pack = self.context_builder.build(
            facts=sampled_facts,
            statistics=statistics,
            category_rules=rules,
            evidence_keys={
                (fact.bucket_id, fact.event_id): reference.event_digest
                for fact, reference in zip(sampled_facts, references, strict=True)
            },
        )
        return ActivityWindowEvidence(
            statistics=statistics,
            evidence_refs=references,
            model_facts=tuple(sampled_facts),
            category_rules=rules,
            context_pack=context_pack,
        )

    async def context_pack(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> ActivityContextPack:
        """Return one bounded, transient chronology for a fixed historical window."""

        evidence = await self.collect_window(start=start, end=end)
        if evidence.context_pack is None:  # Defensive for alternate test implementations.
            return self.context_builder.build(
                facts=evidence.model_facts,
                statistics=evidence.statistics,
                category_rules=evidence.category_rules,
            )
        return evidence.context_pack

    async def statistics(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> ActivityStatistics:
        return (await self.collect_window(start=start, end=end)).statistics

    async def application_usage(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[ActivityRankItem, ...]:
        return (await self.statistics(start=start, end=end)).top_apps

    async def category_usage(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[ActivityRankItem, ...]:
        return (await self.statistics(start=start, end=end)).top_categories

    async def afk_status(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> dict[str, float]:
        window_start, window_end = self._bounded_window(
            start,
            end,
            maximum=self.max_statistics_range,
        )
        facts = await self._fetch_afk_facts(
            start=window_start,
            end=window_end,
            per_bucket_limit=self.max_events_per_bucket,
            require_complete=True,
        )
        active_intervals = self._merged_fact_intervals(
            facts,
            start=window_start,
            end=window_end,
            kind=ObservedFactKind.AFK,
            afk_state=AfkState.ACTIVE,
        )
        afk_intervals = self._merged_fact_intervals(
            facts,
            start=window_start,
            end=window_end,
            kind=ObservedFactKind.AFK,
            afk_state=AfkState.AFK,
        )
        return {
            "active_seconds": sum(
                (stop - begin).total_seconds() for begin, stop in active_intervals
            ),
            "afk_seconds": sum((stop - begin).total_seconds() for begin, stop in afk_intervals),
        }

    async def context_switches(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> dict[str, int]:
        statistics = await self.statistics(start=start, end=end)
        return {
            "application_switches": statistics.app_switch_count,
            "category_switches": statistics.category_switch_count,
            "tab_switches": statistics.tab_switch_count,
            "context_switches": statistics.context_switch_count,
        }

    async def summary_history(
        self,
        *,
        task_type: SummaryTaskType | None = None,
        limit: int = 100,
    ) -> list[ActivitySummaryRevision]:
        return await self.repository.summary_history(task_type=task_type, limit=limit)

    async def list_summaries(
        self,
        *,
        task_type: SummaryTaskType | None = None,
        limit: int = 100,
    ) -> list[ActivitySummaryRevision]:
        return await self.summary_history(task_type=task_type, limit=limit)

    async def get_summary(self, summary_id: str) -> ActivitySummaryRevision | None:
        return await self.repository.get_summary(summary_id)

    async def list_tasks(
        self,
        *,
        statuses: tuple[SummaryTaskStatus, ...] | None = None,
        limit: int = 500,
    ) -> list[ActivitySummaryTask]:
        return await self.repository.list_tasks(statuses=statuses, limit=limit)

    async def trends(
        self,
        *,
        task_type: SummaryTaskType | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        granularity: str | None = None,
        limit: int = 90,
    ) -> list[ActivityTrendPoint]:
        if granularity is not None:
            task_type = {
                "week": SummaryTaskType.WEEKLY,
                "weekly": SummaryTaskType.WEEKLY,
                "month": SummaryTaskType.MONTHLY,
                "monthly": SummaryTaskType.MONTHLY,
            }.get(granularity, task_type)
        points = await self.repository.trends(task_type=task_type, limit=limit * 3)
        window_start = require_aware(start) if start is not None else None
        window_end = require_aware(end) if end is not None else None
        filtered = [
            point
            for point in points
            if (window_start is None or point.window_end > window_start)
            and (window_end is None or point.window_start < window_end)
        ]
        return filtered[-limit:]

    async def _fetch_afk_facts(
        self,
        *,
        start: datetime,
        end: datetime,
        per_bucket_limit: int,
        require_complete: bool = False,
    ) -> list[ObservedActivityFact]:
        segments = await self._selected_afk_segments(start=start, end=end)
        facts: dict[tuple[str, str], ObservedActivityFact] = {}
        for segment in segments:
            events = (
                await self._fetch_bucket_complete(
                    segment.bucket.id,
                    start=segment.start,
                    end=segment.end,
                    limit=per_bucket_limit,
                )
                if require_complete
                else await self.client.events(
                    segment.bucket.id,
                    start=segment.start,
                    end=segment.end,
                    limit=per_bucket_limit,
                )
            )
            for event in events:
                facts[(event.bucket_id, event.id)] = self._fact(
                    event,
                    kind=ObservedFactKind.AFK,
                )
        return sorted(
            facts.values(),
            key=lambda fact: (fact.timestamp, fact.bucket_id, fact.event_id),
        )

    async def _fetch_segment_facts(
        self,
        segments: list[ActivitySourceSegment],
        *,
        start: datetime,
        end: datetime,
        per_bucket_limit: int,
        require_complete: bool = False,
    ) -> list[ObservedActivityFact]:
        facts: dict[tuple[str, str], ObservedActivityFact] = {}
        for segment in segments:
            segment_start = max(start, segment.start)
            segment_end = min(end, segment.end)
            if segment_end <= segment_start:
                continue
            segment_facts = await self._fetch_facts(
                list(segment.buckets),
                start=segment_start,
                end=segment_end,
                per_bucket_limit=per_bucket_limit,
                require_complete=require_complete,
            )
            for fact in segment_facts:
                facts[(fact.bucket_id, fact.event_id)] = fact
            if len(facts) > self.max_total_events:
                raise ActivityQueryLimitExceeded(
                    "ActivityWatch segmented source window exceeded the safety bound"
                )
        return sorted(
            facts.values(),
            key=lambda fact: (fact.timestamp, fact.bucket_id, fact.event_id),
        )

    async def _fetch_facts(
        self,
        buckets: list[ActivityWatchBucket],
        *,
        start: datetime,
        end: datetime,
        per_bucket_limit: int,
        require_complete: bool = False,
    ) -> list[ObservedActivityFact]:
        relevant = [bucket for bucket in buckets if self._bucket_kind(bucket) is not None]
        facts: list[ObservedActivityFact] = []
        for bucket in relevant:
            if require_complete:
                events = await self._fetch_bucket_complete(
                    bucket.id,
                    start=start,
                    end=end,
                    limit=per_bucket_limit,
                )
            else:
                events = await self.client.events(
                    bucket.id,
                    start=start,
                    end=end,
                    limit=per_bucket_limit,
                )
            kind = self._bucket_kind(bucket)
            assert kind is not None
            facts.extend(self._fact(event, kind=kind) for event in events)
            if len(facts) > self.max_total_events:
                raise ActivityQueryLimitExceeded(
                    "ActivityWatch source window exceeded the total event safety bound"
                )
        facts.sort(key=lambda fact: (fact.timestamp, fact.bucket_id, fact.event_id))
        return facts

    async def _fetch_bucket_complete(
        self,
        bucket_id: str,
        *,
        start: datetime,
        end: datetime,
        limit: int,
        depth: int = 0,
    ) -> list[ActivityWatchEvent]:
        events = await self.client.events(
            bucket_id,
            start=start,
            end=end,
            limit=limit,
        )
        if len(events) < limit:
            return events
        if depth >= self.max_slice_depth or end - start <= timedelta(milliseconds=1):
            raise ActivityQueryLimitExceeded(
                f"ActivityWatch bucket {bucket_id} cannot be read completely "
                "within bounded time slices"
            )
        midpoint = start + (end - start) / 2
        left = await self._fetch_bucket_complete(
            bucket_id,
            start=start,
            end=midpoint,
            limit=limit,
            depth=depth + 1,
        )
        right = await self._fetch_bucket_complete(
            bucket_id,
            start=midpoint,
            end=end,
            limit=limit,
            depth=depth + 1,
        )
        merged = {(event.bucket_id, event.id): event for event in (*left, *right)}
        if len(merged) > self.max_total_events:
            raise ActivityQueryLimitExceeded(
                f"ActivityWatch bucket {bucket_id} exceeded the total event safety bound"
            )
        return sorted(
            merged.values(),
            key=lambda event: (event.timestamp, event.id),
        )

    @staticmethod
    def _bucket_kind(bucket: ActivityWatchBucket) -> ObservedFactKind | None:
        identity = " ".join((bucket.id, bucket.type, bucket.client)).casefold()
        if "afk" in identity:
            return ObservedFactKind.AFK
        if "currentwindow" in identity or "watcher-window" in identity:
            return ObservedFactKind.WINDOW
        if "web" in identity or "browser" in identity or "tab" in identity:
            return ObservedFactKind.WEB
        return None

    @staticmethod
    def _fact(
        event: ActivityWatchEvent,
        *,
        kind: ObservedFactKind,
    ) -> ObservedActivityFact:
        data = event.data
        application = _bounded_text(data.get("app"), 500)
        title = _bounded_text(data.get("title"), 4_000)
        url = _bounded_text(data.get("url"), 16_000)
        domain = _bounded_text(data.get("domain"), 500)
        if domain is None and url:
            try:
                domain = urlsplit(url).hostname
            except ValueError:
                domain = None
        status = str(data.get("status", "")).casefold()
        afk_state = (
            AfkState.AFK
            if status in {"afk", "idle"}
            else AfkState.ACTIVE
            if status in {"not-afk", "active", "not_afk"}
            else AfkState.UNKNOWN
        )
        return ObservedActivityFact(
            kind=kind,
            bucket_id=event.bucket_id,
            event_id=event.id,
            timestamp=event.timestamp,
            duration=event.duration,
            application=application,
            title=title,
            url=url,
            domain=domain,
            afk_state=afk_state,
        )

    def _statistics(
        self,
        facts: list[ObservedActivityFact],
        *,
        start: datetime,
        end: datetime,
        category_rules: CategoryRuleVersion,
        category_seconds: dict[str, float],
        source_bucket_ids: tuple[str, ...],
    ) -> ActivityStatistics:
        afk_intervals = self._merged_afk_intervals(facts, start=start, end=end)
        active_intervals = self._merged_fact_intervals(
            facts,
            start=start,
            end=end,
            kind=ObservedFactKind.AFK,
            afk_state=AfkState.ACTIVE,
        )
        afk_seconds = sum((stop - begin).total_seconds() for begin, stop in afk_intervals)
        window_coverage = self._merged_fact_intervals(
            facts,
            start=start,
            end=end,
            kind=ObservedFactKind.WINDOW,
        )
        afk_coverage = self._merged_fact_intervals(
            facts,
            start=start,
            end=end,
            kind=ObservedFactKind.AFK,
        )
        web_coverage = self._merged_fact_intervals(
            facts,
            start=start,
            end=end,
            kind=ObservedFactKind.WEB,
        )
        coverage_intervals = self._intersect_intervals(
            window_coverage,
            afk_coverage,
        )
        observed_seconds = sum((stop - begin).total_seconds() for begin, stop in coverage_intervals)
        window_observed_seconds = sum(
            (stop - begin).total_seconds() for begin, stop in window_coverage
        )
        afk_observed_seconds = sum((stop - begin).total_seconds() for begin, stop in afk_coverage)
        web_observed_seconds = sum((stop - begin).total_seconds() for begin, stop in web_coverage)
        window_seconds = (end - start).total_seconds()
        unobserved_seconds = max(0.0, window_seconds - observed_seconds)
        coverage_ratio = observed_seconds / window_seconds
        coverage_status = (
            ActivityCoverageStatus.NONE
            if observed_seconds <= 0
            else ActivityCoverageStatus.COMPLETE
            if unobserved_seconds <= 0.001
            else ActivityCoverageStatus.PARTIAL
        )
        application_seconds: dict[str, float] = defaultdict(float)
        domain_seconds: dict[str, float] = defaultdict(float)
        active_seconds = 0.0
        browser_seconds = 0.0

        window_facts = [fact for fact in facts if fact.kind is ObservedFactKind.WINDOW]
        web_facts = [fact for fact in facts if fact.kind is ObservedFactKind.WEB]
        for fact in window_facts:
            seconds = self._active_overlap(
                fact,
                start=start,
                end=end,
                active_intervals=active_intervals,
            )
            if seconds <= 0:
                continue
            active_seconds += seconds
            if fact.application:
                application_seconds[fact.application] += seconds
        for fact in web_facts:
            seconds = self._active_overlap(
                fact,
                start=start,
                end=end,
                active_intervals=active_intervals,
            )
            if seconds <= 0:
                continue
            browser_seconds += seconds
            if fact.domain:
                domain_seconds[fact.domain] += seconds

        active_window_facts = [
            fact
            for fact in window_facts
            if self._active_overlap(
                fact,
                start=start,
                end=end,
                active_intervals=active_intervals,
            )
            > 0
        ]
        active_web_facts = [
            fact
            for fact in web_facts
            if self._active_overlap(
                fact,
                start=start,
                end=end,
                active_intervals=active_intervals,
            )
            > 0
        ]
        app_switches = self._count_switches(
            active_window_facts,
            identity=lambda fact: fact.application,
        )
        matcher = CategoryMatcher(category_rules)
        category_switches = self._count_switches(
            active_window_facts,
            identity=matcher.match,
        )
        tab_switches = self._count_switches(
            active_web_facts,
            identity=lambda fact: fact.url or fact.title,
        )
        watermark_builder = hashlib.sha256()
        watermark_builder.update(
            canonical_digest(
                {
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "category_rule_version": category_rules.id,
                    "category_seconds": category_seconds,
                    "source_bucket_ids": source_bucket_ids,
                }
            ).encode("ascii")
        )
        for fact in facts:
            watermark_builder.update(canonical_digest(fact.model_dump(mode="json")).encode("ascii"))
        watermark = watermark_builder.hexdigest()
        return ActivityStatistics(
            window_start=start,
            window_end=end,
            active_seconds=active_seconds,
            afk_seconds=afk_seconds,
            browser_seconds=browser_seconds,
            application_seconds=dict(application_seconds),
            category_seconds=category_seconds,
            domain_seconds=dict(domain_seconds),
            app_switch_count=app_switches,
            category_switch_count=category_switches,
            tab_switch_count=tab_switches,
            context_switch_count=max(app_switches, category_switches) + tab_switches,
            event_count=len(facts),
            observed_seconds=observed_seconds,
            unobserved_seconds=unobserved_seconds,
            window_observed_seconds=window_observed_seconds,
            afk_observed_seconds=afk_observed_seconds,
            web_observed_seconds=web_observed_seconds,
            coverage_ratio=coverage_ratio,
            coverage_status=coverage_status,
            source_bucket_ids=source_bucket_ids,
            source_watermark=watermark,
        )

    async def _server_category_usage(
        self,
        *,
        start: datetime,
        end: datetime,
        category_rules: CategoryRuleVersion,
        window_bucket_id: str,
        afk_bucket_id: str,
    ) -> dict[str, float]:
        normalized = json.loads(category_rules.canonical_json)
        classes = [[item["name"], item["rule"]] for item in normalized]
        classes_json = json.dumps(
            classes,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        # ActivityWatch's query parser consumes regex strings directly. Match
        # aw-client's canonical query expansion so ``\w`` is not delivered as
        # a double-escaped regex to the server.
        classes_query_literal = classes_json.replace("\\\\", "\\")
        window_bucket_literal = json.dumps(window_bucket_id, ensure_ascii=False)
        afk_bucket_literal = json.dumps(afk_bucket_id, ensure_ascii=False)
        result = await self.client.query(
            start=start,
            end=end,
            statements=(
                f"categories = {classes_query_literal};",
                f"events = flood(query_bucket({window_bucket_literal}));",
                f"not_afk = flood(query_bucket({afk_bucket_literal}));",
                'not_afk = filter_keyvals(not_afk, "status", ["not-afk"]);',
                "events = filter_period_intersect(events, not_afk);",
                "events = categorize(events, categories);",
                'events = merge_events_by_keys(events, ["$category"]);',
                "RETURN = sort_by_duration(events);",
            ),
        )
        if len(result) != 1 or not isinstance(result[0], list):
            raise ValueError("ActivityWatch category query returned an invalid result")
        category_seconds: dict[str, float] = defaultdict(float)
        for item in result[0]:
            if not isinstance(item, dict):
                continue
            data = item.get("data")
            duration = item.get("duration")
            if not isinstance(data, dict) or not isinstance(duration, (int, float)):
                continue
            path = data.get("$category")
            if isinstance(path, list) and path:
                name = " / ".join(str(part) for part in path)
            elif isinstance(path, str) and path:
                name = path
            else:
                name = "Uncategorized"
            category_seconds[name] += max(0.0, float(duration))
        return dict(category_seconds)

    async def _selected_segments(
        self,
        *,
        start: datetime,
        end: datetime,
        max_web_buckets: int | None = None,
    ):
        window_start = require_aware(start)
        window_end = require_aware(end)
        info = await self.client.info()
        buckets = await self.client.buckets()
        windows = [
            bucket
            for bucket in buckets
            if self._bucket_kind(bucket) is ObservedFactKind.WINDOW
            and self._bucket_intersects(
                bucket,
                start=window_start,
                end=window_end,
            )
        ]
        afks = [
            bucket
            for bucket in buckets
            if self._bucket_kind(bucket) is ObservedFactKind.AFK
            and self._bucket_intersects(
                bucket,
                start=window_start,
                end=window_end,
            )
        ]
        boundaries = {window_start, window_end}
        for bucket in (*windows, *afks):
            for boundary in (
                bucket.metadata.start or bucket.created,
                bucket.metadata.end,
            ):
                if boundary is not None and window_start < boundary < window_end:
                    boundaries.add(boundary)
        ordered = sorted(boundaries)
        segments: list[ActivitySourceSegment] = []
        for segment_start, segment_end in zip(ordered, ordered[1:], strict=False):
            midpoint = segment_start + (segment_end - segment_start) / 2
            window_candidates = [
                bucket for bucket in windows if self._bucket_covers(bucket, midpoint)
            ]
            pairs = [
                (window, afk)
                for window in window_candidates
                for afk in afks
                if afk.hostname == window.hostname and self._bucket_covers(afk, midpoint)
            ]
            if pairs:
                window, afk = max(
                    pairs,
                    key=lambda pair: self._source_pair_priority(
                        pair,
                        current_hostname=info.hostname,
                    ),
                )
            elif window_candidates:
                window = max(
                    window_candidates,
                    key=lambda bucket: self._bucket_priority(
                        bucket,
                        current_hostname=info.hostname,
                    ),
                )
                afk = None
            else:
                continue
            web_candidates = sorted(
                (
                    bucket
                    for bucket in buckets
                    if self._bucket_kind(bucket) is ObservedFactKind.WEB
                    and bucket.hostname == window.hostname
                    and self._bucket_covers(bucket, midpoint)
                ),
                key=lambda bucket: (
                    bucket.metadata.end or bucket.created or datetime.min.replace(tzinfo=UTC),
                    bucket.id,
                ),
                reverse=True,
            )
            if max_web_buckets is not None:
                web_candidates = web_candidates[:max_web_buckets]
            web = tuple(sorted(web_candidates, key=lambda bucket: bucket.id))
            candidate = ActivitySourceSegment(
                start=segment_start,
                end=segment_end,
                window_bucket=window,
                afk_bucket=afk,
                web_buckets=web,
            )
            if segments and self._same_source_segment(segments[-1], candidate):
                segments[-1] = ActivitySourceSegment(
                    start=segments[-1].start,
                    end=candidate.end,
                    window_bucket=candidate.window_bucket,
                    afk_bucket=candidate.afk_bucket,
                    web_buckets=candidate.web_buckets,
                )
            else:
                segments.append(candidate)
        return info, segments

    async def _selected_afk_segments(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> list[ActivityAfkSegment]:
        window_start = require_aware(start)
        window_end = require_aware(end)
        info = await self.client.info()
        buckets = [
            bucket
            for bucket in await self.client.buckets()
            if self._bucket_kind(bucket) is ObservedFactKind.AFK
            and self._bucket_intersects(
                bucket,
                start=window_start,
                end=window_end,
            )
        ]
        boundaries = {window_start, window_end}
        for bucket in buckets:
            for boundary in (
                bucket.metadata.start or bucket.created,
                bucket.metadata.end,
            ):
                if boundary is not None and window_start < boundary < window_end:
                    boundaries.add(boundary)
        ordered = sorted(boundaries)
        segments: list[ActivityAfkSegment] = []
        for segment_start, segment_end in zip(
            ordered,
            ordered[1:],
            strict=False,
        ):
            midpoint = segment_start + (segment_end - segment_start) / 2
            candidates = [bucket for bucket in buckets if self._bucket_covers(bucket, midpoint)]
            if not candidates:
                continue
            bucket = max(
                candidates,
                key=lambda candidate: self._bucket_priority(
                    candidate,
                    current_hostname=info.hostname,
                ),
            )
            if segments and segments[-1].bucket.id == bucket.id:
                segments[-1] = ActivityAfkSegment(
                    start=segments[-1].start,
                    end=segment_end,
                    bucket=bucket,
                )
            else:
                segments.append(
                    ActivityAfkSegment(
                        start=segment_start,
                        end=segment_end,
                        bucket=bucket,
                    )
                )
        return segments

    @staticmethod
    def _same_source_segment(
        left: ActivitySourceSegment,
        right: ActivitySourceSegment,
    ) -> bool:
        return (
            left.end == right.start
            and left.window_bucket.id == right.window_bucket.id
            and (left.afk_bucket.id if left.afk_bucket else None)
            == (right.afk_bucket.id if right.afk_bucket else None)
            and tuple(bucket.id for bucket in left.web_buckets)
            == tuple(bucket.id for bucket in right.web_buckets)
        )

    @staticmethod
    def _bucket_priority(
        bucket: ActivityWatchBucket,
        *,
        current_hostname: str,
    ) -> tuple[int, datetime, str]:
        return (
            int(bucket.hostname == current_hostname),
            bucket.metadata.end or bucket.created or datetime.min.replace(tzinfo=UTC),
            bucket.id,
        )

    def _source_pair_priority(
        self,
        pair: tuple[ActivityWatchBucket, ActivityWatchBucket],
        *,
        current_hostname: str,
    ) -> tuple[int, datetime, str, str]:
        window, afk = pair
        return (
            int(window.hostname == current_hostname),
            max(
                value
                for value in (
                    window.metadata.end,
                    afk.metadata.end,
                    window.created,
                    afk.created,
                    datetime.min.replace(tzinfo=UTC),
                )
                if value is not None
            ),
            window.id,
            afk.id,
        )

    @staticmethod
    def _bucket_intersects(
        bucket: ActivityWatchBucket,
        *,
        start: datetime | None,
        end: datetime | None,
    ) -> bool:
        if start is None or end is None:
            return True
        bucket_start = bucket.metadata.start or bucket.created
        bucket_end = bucket.metadata.end
        if bucket_start is None and bucket_end is None:
            return True
        if bucket_start is not None and bucket_start >= end:
            return False
        return bucket_end is None or bucket_end > start

    @staticmethod
    def _bucket_covers(bucket: ActivityWatchBucket, instant: datetime) -> bool:
        bucket_start = bucket.metadata.start or bucket.created
        bucket_end = bucket.metadata.end
        return (bucket_start is None or bucket_start <= instant) and (
            bucket_end is None or bucket_end > instant
        )

    @staticmethod
    def _segment_bucket_ids(
        segments: list[ActivitySourceSegment],
    ) -> tuple[str, ...]:
        return tuple(dict.fromkeys(bucket.id for segment in segments for bucket in segment.buckets))

    @staticmethod
    def _merged_afk_intervals(
        facts: list[ObservedActivityFact],
        *,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, datetime]]:
        intervals = sorted(
            (
                (max(start, fact.timestamp), min(end, fact.ended_at))
                for fact in facts
                if fact.kind is ObservedFactKind.AFK
                and fact.afk_state is AfkState.AFK
                and fact.ended_at > start
                and fact.timestamp < end
            ),
            key=lambda item: item[0],
        )
        merged: list[tuple[datetime, datetime]] = []
        for begin, stop in intervals:
            if stop <= begin:
                continue
            if not merged or begin > merged[-1][1]:
                merged.append((begin, stop))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        return merged

    @staticmethod
    def _merged_fact_intervals(
        facts: list[ObservedActivityFact],
        *,
        start: datetime,
        end: datetime,
        kind: ObservedFactKind,
        afk_state: AfkState | None = None,
    ) -> list[tuple[datetime, datetime]]:
        intervals = sorted(
            (
                (max(start, fact.timestamp), min(end, fact.ended_at))
                for fact in facts
                if fact.kind is kind
                and (afk_state is None or fact.afk_state is afk_state)
                and fact.ended_at > start
                and fact.timestamp < end
            ),
            key=lambda item: item[0],
        )
        merged: list[tuple[datetime, datetime]] = []
        for begin, stop in intervals:
            if stop <= begin:
                continue
            if not merged or begin > merged[-1][1]:
                merged.append((begin, stop))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        return merged

    @staticmethod
    def _intersect_intervals(
        left: list[tuple[datetime, datetime]],
        right: list[tuple[datetime, datetime]],
    ) -> list[tuple[datetime, datetime]]:
        intersections: list[tuple[datetime, datetime]] = []
        left_index = 0
        right_index = 0
        while left_index < len(left) and right_index < len(right):
            begin = max(left[left_index][0], right[right_index][0])
            stop = min(left[left_index][1], right[right_index][1])
            if stop > begin:
                intersections.append((begin, stop))
            if left[left_index][1] <= right[right_index][1]:
                left_index += 1
            else:
                right_index += 1
        return intersections

    @staticmethod
    def _active_overlap(
        fact: ObservedActivityFact,
        *,
        start: datetime,
        end: datetime,
        active_intervals: list[tuple[datetime, datetime]],
    ) -> float:
        begin = max(start, fact.timestamp)
        stop = min(end, fact.ended_at)
        if stop <= begin:
            return 0.0
        return sum(
            max(
                0.0,
                (min(stop, active_end) - max(begin, active_start)).total_seconds(),
            )
            for active_start, active_end in active_intervals
        )

    @staticmethod
    def _count_switches(facts, *, identity) -> int:
        previous: str | None = None
        switches = 0
        for fact in sorted(facts, key=lambda item: (item.timestamp, item.event_id)):
            current = identity(fact)
            if not current:
                continue
            if previous is not None and current != previous:
                switches += 1
            previous = current
        return switches

    @staticmethod
    def _sample_facts(
        facts: list[ObservedActivityFact],
        limit: int,
    ) -> list[ObservedActivityFact]:
        if len(facts) <= limit:
            return list(facts)
        if limit == 1:
            return [facts[-1]]
        indexes = {round(index * (len(facts) - 1) / (limit - 1)) for index in range(limit)}
        return [facts[index] for index in sorted(indexes)]

    @staticmethod
    def _fields_used(fact: ObservedActivityFact) -> tuple[str, ...]:
        fields = ["kind", "timestamp", "duration"]
        for field in ("application", "title", "url", "domain", "afk_state"):
            value = getattr(fact, field)
            if value is not None and value != AfkState.UNKNOWN:
                fields.append(field)
        return tuple(fields)

    @staticmethod
    def _fact_search_text(fact: ObservedActivityFact) -> str:
        return " ".join(
            value
            for value in (
                fact.application,
                fact.title,
                fact.domain,
            )
            if value
        ).casefold()

    @staticmethod
    def _bounded_window(
        start: datetime,
        end: datetime,
        *,
        maximum: timedelta,
    ) -> tuple[datetime, datetime]:
        window_start = require_aware(start)
        window_end = require_aware(end)
        if window_end <= window_start:
            raise ValueError("end must be after start")
        if window_end - window_start > maximum:
            raise ValueError(f"activity query exceeds the {maximum.days}-day bound")
        return window_start, window_end


def _bounded_text(value, maximum: int) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:maximum]
