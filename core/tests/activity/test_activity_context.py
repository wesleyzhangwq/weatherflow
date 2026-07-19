from datetime import UTC, datetime, timedelta

from weatherflow.activity import (
    ActivityCoverageStatus,
    ActivityStatistics,
    AfkState,
    ObservedActivityFact,
)
from weatherflow.activity.categories import category_rule_version
from weatherflow.activity.context import ActivityContextPackBuilder


def _fact(
    *,
    kind: str,
    timestamp: datetime,
    duration: float,
    event_id: str,
    application: str | None = None,
    title: str | None = None,
    domain: str | None = None,
    afk_state: AfkState = AfkState.UNKNOWN,
) -> ObservedActivityFact:
    return ObservedActivityFact(
        kind=kind,
        bucket_id=f"{kind}-bucket",
        event_id=event_id,
        timestamp=timestamp,
        duration=duration,
        application=application,
        title=title,
        domain=domain,
        afk_state=afk_state,
    )


def test_context_pack_preserves_bounded_precise_observations_and_category_sequence() -> None:
    start = datetime(2026, 7, 18, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    rules = category_rule_version(
        [
            {
                "name": ["Work", "Development"],
                "rule": {
                    "type": "regex",
                    "regex": "Code|WeatherFlow",
                    "ignore_case": True,
                },
            },
            {
                "name": ["Research"],
                "rule": {
                    "type": "regex",
                    "regex": "Docs|reference",
                    "ignore_case": True,
                },
            },
        ]
    )
    facts = (
        _fact(
            kind="window",
            timestamp=start,
            duration=600,
            event_id="window-1",
            application="Code",
            title="WeatherFlow — secret=must-redact",
        ),
        _fact(
            kind="afk",
            timestamp=start,
            duration=1_200,
            event_id="afk-active",
            afk_state=AfkState.ACTIVE,
        ),
        _fact(
            kind="window",
            timestamp=start + timedelta(minutes=10),
            duration=600,
            event_id="window-2",
            application="Browser",
            title="Docs",
        ),
        _fact(
            kind="web",
            timestamp=start + timedelta(minutes=10),
            duration=600,
            event_id="web-1",
            title="Reference",
            domain="docs.example",
        ),
        _fact(
            kind="afk",
            timestamp=start + timedelta(minutes=20),
            duration=600,
            event_id="afk-away",
            afk_state=AfkState.AFK,
        ),
    )
    statistics = ActivityStatistics(
        window_start=start,
        window_end=end,
        active_seconds=1_200,
        afk_seconds=600,
        application_seconds={"Code": 600, "Browser": 600},
        category_seconds={"Work / Development": 600, "Research": 600},
        app_switch_count=1,
        category_switch_count=1,
        tab_switch_count=0,
        context_switch_count=1,
        observed_seconds=1_800,
        window_observed_seconds=1_200,
        afk_observed_seconds=1_800,
        web_observed_seconds=600,
        coverage_ratio=1,
        coverage_status=ActivityCoverageStatus.COMPLETE,
        source_watermark="a" * 64,
    )

    pack = ActivityContextPackBuilder().build(
        facts=facts,
        statistics=statistics,
        category_rules=rules,
    )

    assert pack.window_start.isoformat().endswith("+08:00")
    assert pack.window_end.isoformat().endswith("+08:00")
    assert pack.category_rule_version == rules.id
    assert [episode.category for episode in pack.category_episodes] == [
        "Work / Development",
        "Research",
    ]
    assert pack.category_episodes[0].duration_seconds == 600
    assert pack.category_transitions[0].occurred_at == start + timedelta(minutes=10)
    assert pack.category_transitions[0].from_category == "Work / Development"
    assert pack.category_transitions[0].to_category == "Research"
    assert [interval.state for interval in pack.afk_intervals] == [
        AfkState.ACTIVE,
        AfkState.AFK,
    ]
    assert pack.afk_intervals[-1].duration_seconds == 600
    assert any(item.application == "Code" for item in pack.evidence)
    assert any(item.title == "WeatherFlow — [REDACTED]" for item in pack.evidence)
    assert all(len(item.evidence_key) == 64 for item in pack.evidence)
    serialized = pack.model_dump_json()
    assert "window-bucket" not in serialized
    assert "window-1" not in serialized
    assert "must-redact" not in serialized
    assert "state_label" not in serialized
    assert "confidence" not in serialized


def test_context_pack_enforces_fact_and_byte_bounds_without_losing_window_statistics() -> None:
    start = datetime(2026, 7, 18, 0, tzinfo=UTC)
    end = start + timedelta(hours=6)
    facts = tuple(
        _fact(
            kind="window",
            timestamp=start + timedelta(seconds=index * 30),
            duration=30,
            event_id=f"event-{index}",
            application=f"App {index % 5}",
            title=("Document " + str(index) + " ") * 100,
        )
        for index in range(1_000)
    )
    statistics = ActivityStatistics(
        window_start=start,
        window_end=end,
        active_seconds=21_600,
        application_seconds={f"App {index}": 4_320 for index in range(5)},
        category_seconds={"Uncategorized": 21_600},
        observed_seconds=21_600,
        window_observed_seconds=21_600,
        afk_observed_seconds=21_600,
        coverage_ratio=1,
        coverage_status=ActivityCoverageStatus.COMPLETE,
        source_watermark="b" * 64,
    )

    pack = ActivityContextPackBuilder().build(
        facts=facts,
        statistics=statistics,
        category_rules=category_rule_version([]),
    )

    assert len(pack.evidence) <= ActivityContextPackBuilder.max_evidence
    assert len(pack.model_dump_json().encode("utf-8")) <= ActivityContextPackBuilder.max_pack_bytes
    assert pack.truncated is True
    assert pack.statistics.active_seconds == 21_600
    assert pack.statistics.coverage_ratio == 1


def test_context_pack_merged_spans_do_not_count_unobserved_gaps_as_duration() -> None:
    start = datetime(2026, 7, 18, 0, tzinfo=UTC)
    end = start + timedelta(minutes=3)
    facts = (
        _fact(
            kind="window",
            timestamp=start,
            duration=60,
            event_id="window-a",
            application="Code",
        ),
        _fact(
            kind="afk",
            timestamp=start,
            duration=60,
            event_id="active-a",
            afk_state=AfkState.ACTIVE,
        ),
        _fact(
            kind="window",
            timestamp=start + timedelta(minutes=2),
            duration=60,
            event_id="window-b",
            application="Code",
        ),
        _fact(
            kind="afk",
            timestamp=start + timedelta(minutes=2),
            duration=60,
            event_id="active-b",
            afk_state=AfkState.ACTIVE,
        ),
    )
    statistics = ActivityStatistics(
        window_start=start,
        window_end=end,
        active_seconds=120,
        application_seconds={"Code": 120},
        category_seconds={"Work": 120},
        observed_seconds=120,
        unobserved_seconds=60,
        window_observed_seconds=120,
        afk_observed_seconds=120,
        coverage_ratio=2 / 3,
        coverage_status=ActivityCoverageStatus.PARTIAL,
        source_watermark="c" * 64,
    )
    rules = category_rule_version(
        [
            {
                "name": ["Work"],
                "rule": {"type": "regex", "regex": "Code"},
            }
        ]
    )

    pack = ActivityContextPackBuilder().build(
        facts=facts,
        statistics=statistics,
        category_rules=rules,
    )

    assert len(pack.category_episodes) == 1
    assert (pack.category_episodes[0].end - pack.category_episodes[0].start).total_seconds() == 180
    assert pack.category_episodes[0].duration_seconds == 120
    assert len(pack.afk_intervals) == 1
    assert (pack.afk_intervals[0].end - pack.afk_intervals[0].start).total_seconds() == 180
    assert pack.afk_intervals[0].duration_seconds == 120


def test_context_pack_clips_model_observations_to_the_requested_window() -> None:
    start = datetime(2026, 7, 18, 0, tzinfo=UTC)
    end = start + timedelta(minutes=3)
    facts = (
        _fact(
            kind="window",
            timestamp=start - timedelta(minutes=1),
            duration=300,
            event_id="crossing-window",
            application="Code",
        ),
        _fact(
            kind="afk",
            timestamp=start - timedelta(minutes=1),
            duration=300,
            event_id="crossing-active",
            afk_state=AfkState.ACTIVE,
        ),
    )
    statistics = ActivityStatistics(
        window_start=start,
        window_end=end,
        active_seconds=180,
        application_seconds={"Code": 180},
        category_seconds={"Work": 180},
        observed_seconds=180,
        window_observed_seconds=180,
        afk_observed_seconds=180,
        coverage_ratio=1,
        coverage_status=ActivityCoverageStatus.COMPLETE,
        source_watermark="d" * 64,
    )
    rules = category_rule_version([{"name": ["Work"], "rule": {"type": "regex", "regex": "Code"}}])

    pack = ActivityContextPackBuilder().build(
        facts=facts,
        statistics=statistics,
        category_rules=rules,
    )

    assert all(item.timestamp == start for item in pack.evidence)
    assert all(item.duration == 180 for item in pack.evidence)
    assert pack.category_episodes[0].start == start
    assert pack.category_episodes[0].end == end
    assert pack.category_episodes[0].duration_seconds == 180
