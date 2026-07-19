from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from weatherflow.activity.categories import CategoryMatcher
from weatherflow.activity.models import (
    ACTIVITY_TIMEZONE,
    ActivityCoverageStatus,
    ActivityStatistics,
    AfkState,
    CategoryRuleVersion,
    ObservedActivityFact,
    ObservedFactKind,
    canonical_digest,
)
from weatherflow.activity.sanitizer import ActivitySanitizer

_LOCAL_TIMEZONE = ZoneInfo(ACTIVITY_TIMEZONE)


def _require_local_aware(value: datetime) -> datetime:
    """Validate without normalizing away the explicit Shanghai offset.

    The durable domain models normalize instants to UTC.  Context packs are a
    transient, human-facing chronology, so preserving the local offset makes
    every timestamp independently interpretable by the model.
    """

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class ActivityContextStatistics(BaseModel):
    """Safe aggregate fields that may survive a transient context read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_seconds: float = Field(ge=0)
    afk_seconds: float = Field(ge=0)
    browser_seconds: float = Field(ge=0)
    observed_seconds: float = Field(ge=0)
    unobserved_seconds: float = Field(ge=0)
    coverage_ratio: float = Field(ge=0, le=1)
    coverage_status: ActivityCoverageStatus
    category_seconds: dict[str, float]
    app_switch_count: int = Field(ge=0)
    category_switch_count: int = Field(ge=0)
    tab_switch_count: int = Field(ge=0)


class ActivityContextEvidence(BaseModel):
    """One sanitized, model-only observation with an opaque evidence key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_key: str = Field(min_length=64, max_length=64)
    kind: ObservedFactKind
    timestamp: datetime
    duration: float = Field(ge=0)
    category: str | None = None
    application: str | None = Field(default=None, max_length=160)
    title: str | None = Field(default=None, max_length=320)
    url: str | None = Field(default=None, max_length=800)
    domain: str | None = Field(default=None, max_length=200)
    afk_state: AfkState = AfkState.UNKNOWN

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        return _require_local_aware(value)


class ActivityCategoryEpisode(BaseModel):
    """A deterministic Category interval, never a human-state hypothesis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: datetime
    end: datetime
    duration_seconds: float = Field(ge=0)
    category: str
    evidence_keys: tuple[str, ...] = Field(max_length=8)

    @field_validator("start", "end")
    @classmethod
    def aware_timestamps(cls, value: datetime) -> datetime:
        return _require_local_aware(value)


class ActivityCategoryTransition(BaseModel):
    """A Category label change observed between adjacent active intervals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    occurred_at: datetime
    from_category: str
    to_category: str
    gap_seconds: float = Field(ge=0)
    evidence_keys: tuple[str, ...] = Field(min_length=1, max_length=2)

    @field_validator("occurred_at")
    @classmethod
    def aware_occurred_at(cls, value: datetime) -> datetime:
        return _require_local_aware(value)


class ActivityAfkInterval(BaseModel):
    """A bounded model-only projection of directly observed AFK heartbeat intervals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: datetime
    end: datetime
    duration_seconds: float = Field(ge=0)
    state: AfkState
    evidence_keys: tuple[str, ...] = Field(max_length=8)

    @field_validator("start", "end")
    @classmethod
    def aware_timestamps(cls, value: datetime) -> datetime:
        return _require_local_aware(value)


class ActivityContextPack(BaseModel):
    """Bounded evidence pack for one tool-free model turn.

    Raw application/title/URL values in ``evidence`` are transient. The safe
    durable projection is constructed independently by the activity executor.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    data_classification: str = "untrusted_activity_context"
    instructions_allowed: bool = False
    window_start: datetime
    window_end: datetime
    category_rule_version: str = Field(min_length=64, max_length=64)
    statistics: ActivityContextStatistics
    category_episodes: tuple[ActivityCategoryEpisode, ...]
    category_transitions: tuple[ActivityCategoryTransition, ...]
    afk_intervals: tuple[ActivityAfkInterval, ...]
    evidence: tuple[ActivityContextEvidence, ...]
    redaction_count: int = Field(ge=0)
    truncated: bool = False

    @field_validator("window_start", "window_end")
    @classmethod
    def aware_window(cls, value: datetime) -> datetime:
        return _require_local_aware(value)


class ActivityContextPackBuilder:
    """Build a deterministic time-structured pack without inferring human state."""

    max_evidence = 80
    max_category_episodes = 24
    max_category_transitions = 24
    max_afk_intervals = 24
    max_pack_bytes = 128 * 1024
    merge_gap = timedelta(seconds=90)

    def __init__(self, *, sanitizer: ActivitySanitizer | None = None) -> None:
        self.sanitizer = sanitizer or ActivitySanitizer()

    def build(
        self,
        *,
        facts: Sequence[ObservedActivityFact],
        statistics: ActivityStatistics,
        category_rules: CategoryRuleVersion,
        evidence_keys: Mapping[tuple[str, str], str] | None = None,
    ) -> ActivityContextPack:
        ordered = sorted(
            (
                fact
                for fact in facts
                if fact.timestamp < statistics.window_end
                and fact.ended_at > statistics.window_start
            ),
            key=lambda fact: (fact.timestamp, fact.bucket_id, fact.event_id),
        )
        matcher = CategoryMatcher(category_rules)
        evidence_facts = self._select_evidence(ordered, limit=self.max_evidence)
        evidence, redaction_count = self._evidence(
            evidence_facts,
            matcher=matcher,
            evidence_keys=evidence_keys,
            window_start=statistics.window_start,
            window_end=statistics.window_end,
        )
        evidence_key_by_identity = {
            (fact.bucket_id, fact.event_id): self._resolved_evidence_key(
                fact,
                evidence_keys=evidence_keys,
            )
            for fact in ordered
        }
        active_intervals = self._state_intervals(
            ordered,
            state=AfkState.ACTIVE,
            start=statistics.window_start,
            end=statistics.window_end,
        )
        episodes_all = self._category_episodes(
            ordered,
            active_intervals=active_intervals,
            matcher=matcher,
            evidence_keys=evidence_key_by_identity,
            start=statistics.window_start,
            end=statistics.window_end,
        )
        episodes = self._bounded_records(episodes_all, self.max_category_episodes)
        transitions_all = self._category_transitions(episodes_all)
        transitions = self._bounded_records(
            transitions_all,
            self.max_category_transitions,
        )
        afk_all = self._afk_intervals(
            ordered,
            evidence_keys=evidence_key_by_identity,
            start=statistics.window_start,
            end=statistics.window_end,
        )
        afk_intervals = self._bounded_records(afk_all, self.max_afk_intervals)
        truncated = any(
            (
                len(evidence_facts) < len(ordered),
                len(episodes) < len(episodes_all),
                len(transitions) < len(transitions_all),
                len(afk_intervals) < len(afk_all),
            )
        )
        pack = self._pack(
            statistics=statistics,
            category_rules=category_rules,
            evidence=evidence,
            episodes=episodes,
            transitions=transitions,
            afk_intervals=afk_intervals,
            redaction_count=redaction_count,
            truncated=truncated,
        )
        while len(pack.model_dump_json().encode("utf-8")) > self.max_pack_bytes and evidence:
            evidence = self._thin(evidence)
            truncated = True
            pack = self._pack(
                statistics=statistics,
                category_rules=category_rules,
                evidence=evidence,
                episodes=episodes,
                transitions=transitions,
                afk_intervals=afk_intervals,
                redaction_count=redaction_count,
                truncated=truncated,
            )
        if len(pack.model_dump_json().encode("utf-8")) > self.max_pack_bytes:
            raise ValueError("activity context aggregate exceeded the model request bound")
        return pack

    @staticmethod
    def _evidence_key(fact: ObservedActivityFact) -> str:
        return canonical_digest(
            {
                "bucket_id": fact.bucket_id,
                "event_id": fact.event_id,
                "timestamp": fact.timestamp.isoformat(),
                "duration": fact.duration,
                "kind": fact.kind.value,
            }
        )

    def _resolved_evidence_key(
        self,
        fact: ObservedActivityFact,
        *,
        evidence_keys: Mapping[tuple[str, str], str] | None,
    ) -> str:
        if evidence_keys is not None:
            value = evidence_keys.get((fact.bucket_id, fact.event_id))
            if isinstance(value, str) and len(value) == 64:
                return value
        return self._evidence_key(fact)

    def _evidence(
        self,
        facts: Sequence[ObservedActivityFact],
        *,
        matcher: CategoryMatcher,
        evidence_keys: Mapping[tuple[str, str], str] | None,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[tuple[ActivityContextEvidence, ...], int]:
        projected: list[ActivityContextEvidence] = []
        redactions = 0
        for fact in facts:
            sanitized = self.sanitizer.sanitize(fact)
            event = sanitized.event
            redactions += sanitized.redaction_count
            overlap_start = max(fact.timestamp, window_start)
            overlap_end = min(fact.ended_at, window_end)
            if overlap_end <= overlap_start:
                continue
            projected.append(
                ActivityContextEvidence(
                    evidence_key=self._resolved_evidence_key(
                        fact,
                        evidence_keys=evidence_keys,
                    ),
                    kind=fact.kind,
                    timestamp=overlap_start.astimezone(_LOCAL_TIMEZONE),
                    duration=(overlap_end - overlap_start).total_seconds(),
                    category=(
                        matcher.match(fact)
                        if fact.kind in {ObservedFactKind.WINDOW, ObservedFactKind.WEB}
                        else None
                    ),
                    application=self._bounded(event.get("application"), 160),
                    title=self._bounded(event.get("title"), 320),
                    # A domain is sufficient for the context chronology. Full
                    # paths and query strings add privacy risk without helping
                    # the model distinguish the observed source.
                    url=None,
                    domain=self._bounded(event.get("domain"), 200),
                    afk_state=fact.afk_state,
                )
            )
        return tuple(projected), redactions

    def _category_episodes(
        self,
        facts: Sequence[ObservedActivityFact],
        *,
        active_intervals: Sequence[tuple[datetime, datetime]],
        matcher: CategoryMatcher,
        evidence_keys: dict[tuple[str, str], str],
        start: datetime,
        end: datetime,
    ) -> tuple[ActivityCategoryEpisode, ...]:
        pieces: list[ActivityCategoryEpisode] = []
        for fact in facts:
            if fact.kind is not ObservedFactKind.WINDOW:
                continue
            fact_start = max(start, fact.timestamp)
            fact_end = min(end, fact.ended_at)
            for active_start, active_end in active_intervals:
                piece_start = max(fact_start, active_start)
                piece_end = min(fact_end, active_end)
                if piece_end <= piece_start:
                    continue
                pieces.append(
                    ActivityCategoryEpisode(
                        start=piece_start.astimezone(_LOCAL_TIMEZONE),
                        end=piece_end.astimezone(_LOCAL_TIMEZONE),
                        duration_seconds=(piece_end - piece_start).total_seconds(),
                        category=matcher.match(fact),
                        evidence_keys=(evidence_keys[(fact.bucket_id, fact.event_id)],),
                    )
                )
        merged: list[ActivityCategoryEpisode] = []
        for piece in sorted(pieces, key=lambda item: (item.start, item.end, item.category)):
            previous = merged[-1] if merged else None
            if (
                previous is not None
                and previous.category == piece.category
                and piece.start <= previous.end + self.merge_gap
            ):
                combined_end = max(previous.end, piece.end)
                newly_observed_seconds = max(
                    0.0,
                    (piece.end - max(piece.start, previous.end)).total_seconds(),
                )
                merged[-1] = ActivityCategoryEpisode(
                    start=previous.start,
                    end=combined_end,
                    duration_seconds=previous.duration_seconds + newly_observed_seconds,
                    category=previous.category,
                    evidence_keys=tuple(
                        dict.fromkeys((*previous.evidence_keys, *piece.evidence_keys))
                    )[:8],
                )
            else:
                merged.append(piece)
        return tuple(merged)

    @staticmethod
    def _category_transitions(
        episodes: Sequence[ActivityCategoryEpisode],
    ) -> tuple[ActivityCategoryTransition, ...]:
        transitions: list[ActivityCategoryTransition] = []
        for previous, current in zip(episodes, episodes[1:], strict=False):
            if previous.category == current.category:
                continue
            transitions.append(
                ActivityCategoryTransition(
                    occurred_at=current.start,
                    from_category=previous.category,
                    to_category=current.category,
                    gap_seconds=max(0.0, (current.start - previous.end).total_seconds()),
                    evidence_keys=(previous.evidence_keys[-1], current.evidence_keys[0]),
                )
            )
        return tuple(transitions)

    def _afk_intervals(
        self,
        facts: Sequence[ObservedActivityFact],
        *,
        evidence_keys: dict[tuple[str, str], str],
        start: datetime,
        end: datetime,
    ) -> tuple[ActivityAfkInterval, ...]:
        intervals: list[ActivityAfkInterval] = []
        for fact in facts:
            if fact.kind is not ObservedFactKind.AFK or fact.afk_state is AfkState.UNKNOWN:
                continue
            begin = max(start, fact.timestamp)
            stop = min(end, fact.ended_at)
            if stop <= begin:
                continue
            item = ActivityAfkInterval(
                start=begin.astimezone(_LOCAL_TIMEZONE),
                end=stop.astimezone(_LOCAL_TIMEZONE),
                duration_seconds=(stop - begin).total_seconds(),
                state=fact.afk_state,
                evidence_keys=(evidence_keys[(fact.bucket_id, fact.event_id)],),
            )
            previous = intervals[-1] if intervals else None
            if (
                previous is not None
                and previous.state is item.state
                and item.start <= previous.end + self.merge_gap
            ):
                combined_end = max(previous.end, item.end)
                newly_observed_seconds = max(
                    0.0,
                    (item.end - max(item.start, previous.end)).total_seconds(),
                )
                intervals[-1] = ActivityAfkInterval(
                    start=previous.start,
                    end=combined_end,
                    duration_seconds=previous.duration_seconds + newly_observed_seconds,
                    state=previous.state,
                    evidence_keys=tuple(
                        dict.fromkeys((*previous.evidence_keys, *item.evidence_keys))
                    )[:8],
                )
            else:
                intervals.append(item)
        return tuple(intervals)

    @staticmethod
    def _state_intervals(
        facts: Sequence[ObservedActivityFact],
        *,
        state: AfkState,
        start: datetime,
        end: datetime,
    ) -> tuple[tuple[datetime, datetime], ...]:
        candidates = sorted(
            (
                (max(start, fact.timestamp), min(end, fact.ended_at))
                for fact in facts
                if fact.kind is ObservedFactKind.AFK and fact.afk_state is state
            ),
            key=lambda item: item[0],
        )
        merged: list[tuple[datetime, datetime]] = []
        for begin, stop in candidates:
            if stop <= begin:
                continue
            if merged and begin <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
            else:
                merged.append((begin, stop))
        return tuple(merged)

    def _pack(
        self,
        *,
        statistics: ActivityStatistics,
        category_rules: CategoryRuleVersion,
        evidence: Sequence[ActivityContextEvidence],
        episodes: Sequence[ActivityCategoryEpisode],
        transitions: Sequence[ActivityCategoryTransition],
        afk_intervals: Sequence[ActivityAfkInterval],
        redaction_count: int,
        truncated: bool,
    ) -> ActivityContextPack:
        return ActivityContextPack(
            window_start=statistics.window_start.astimezone(_LOCAL_TIMEZONE),
            window_end=statistics.window_end.astimezone(_LOCAL_TIMEZONE),
            category_rule_version=category_rules.id,
            statistics=ActivityContextStatistics(
                active_seconds=statistics.active_seconds,
                afk_seconds=statistics.afk_seconds,
                browser_seconds=statistics.browser_seconds,
                observed_seconds=statistics.observed_seconds,
                unobserved_seconds=statistics.unobserved_seconds,
                coverage_ratio=statistics.coverage_ratio,
                coverage_status=statistics.coverage_status,
                category_seconds=statistics.category_seconds,
                app_switch_count=statistics.app_switch_count,
                category_switch_count=statistics.category_switch_count,
                tab_switch_count=statistics.tab_switch_count,
            ),
            category_episodes=tuple(episodes),
            category_transitions=tuple(transitions),
            afk_intervals=tuple(afk_intervals),
            evidence=tuple(evidence),
            redaction_count=redaction_count,
            truncated=truncated,
        )

    def _select_evidence(
        self,
        facts: Sequence[ObservedActivityFact],
        *,
        limit: int,
    ) -> tuple[ObservedActivityFact, ...]:
        if len(facts) <= limit:
            return tuple(facts)
        identities: list[tuple[object, ...]] = []
        transition_indexes: set[int] = set()
        previous: tuple[object, ...] | None = None
        for index, fact in enumerate(facts):
            identity = (
                fact.kind,
                fact.application,
                fact.domain,
                fact.afk_state,
            )
            identities.append(identity)
            if previous is not None and identity != previous:
                transition_indexes.update((index - 1, index))
            previous = identity
        selected = {0, len(facts) - 1, *transition_indexes}
        longest = sorted(
            range(len(facts)),
            key=lambda index: (-facts[index].duration, facts[index].timestamp, index),
        )
        selected.update(longest[: max(1, limit // 4)])
        if len(selected) < limit:
            for slot in range(limit):
                selected.add(round(slot * (len(facts) - 1) / max(1, limit - 1)))
                if len(selected) >= limit:
                    break
        if len(selected) > limit:
            priority = sorted(
                selected,
                key=lambda index: (
                    index not in {0, len(facts) - 1},
                    index not in transition_indexes,
                    -facts[index].duration,
                    index,
                ),
            )[:limit]
            selected = set(priority)
        return tuple(facts[index] for index in sorted(selected))

    @staticmethod
    def _bounded_records(records: Sequence, limit: int) -> tuple:
        if len(records) <= limit:
            return tuple(records)
        if limit <= 1:
            return (records[-1],)
        indexes = {round(index * (len(records) - 1) / (limit - 1)) for index in range(limit)}
        return tuple(records[index] for index in sorted(indexes))

    @staticmethod
    def _thin(values: Sequence) -> tuple:
        if len(values) <= 2:
            return tuple(values[:1])
        return (values[0], *values[1:-1:2], values[-1])

    @staticmethod
    def _bounded(value: object, maximum: int) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        return value[:maximum]


def activity_context_pack_output_schema() -> dict:
    """Return the strict JSON Schema frozen into the built-in ToolSpec."""

    return ActivityContextPack.model_json_schema()


def safe_category_projection(pack: ActivityContextPack) -> dict[str, object]:
    """Drop raw evidence and AFK intervals before checkpoint persistence."""

    return {
        "operation": "context_pack",
        "data_classification": "derived_activity_statistics",
        "window_start": pack.window_start.isoformat(),
        "window_end": pack.window_end.isoformat(),
        "category_rule_version": pack.category_rule_version,
        "fact_count": len(pack.evidence),
        "active_seconds": pack.statistics.active_seconds,
        "afk_seconds": pack.statistics.afk_seconds,
        "coverage_ratio": pack.statistics.coverage_ratio,
        "coverage_status": pack.statistics.coverage_status.value,
        "app_switch_count": pack.statistics.app_switch_count,
        "category_switch_count": pack.statistics.category_switch_count,
        "tab_switch_count": pack.statistics.tab_switch_count,
        "category_seconds": dict(pack.statistics.category_seconds),
        "category_episodes": [
            {
                "start": episode.start.isoformat(),
                "end": episode.end.isoformat(),
                "duration_seconds": episode.duration_seconds,
                "category": episode.category,
            }
            for episode in pack.category_episodes
        ],
        "category_transitions": [
            {
                "occurred_at": transition.occurred_at.isoformat(),
                "from_category": transition.from_category,
                "to_category": transition.to_category,
                "gap_seconds": transition.gap_seconds,
            }
            for transition in pack.category_transitions
        ],
        "truncated": pack.truncated,
        "redaction_count": pack.redaction_count,
    }
