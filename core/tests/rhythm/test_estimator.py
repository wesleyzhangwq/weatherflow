from datetime import UTC, datetime, timedelta

import pytest

from weatherflow.rhythm import (
    ActivityMetadata,
    AppCategory,
    CheckInSignal,
    CorrectionSignal,
    RhythmEstimator,
    WeatherScene,
    project_policy,
    project_weather,
)

NOW = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)


def checkin(text: str, event_id: str = "event-1"):
    return (event_id, CheckInSignal(text=text, observed_at=NOW))


@pytest.mark.parametrize(
    ("text", "scene"),
    [
        ("I am overloaded and exhausted", WeatherScene.STORM),
        ("I keep getting interrupted and fragmented", WeatherScene.FOG),
        ("I am blocked and stuck", WeatherScene.STILL),
        ("I am focused and in flow", WeatherScene.CLEAR),
        ("I need recovery and rest", WeatherScene.NIGHT),
        ("Today feels steady", WeatherScene.FAIR),
    ],
)
def test_deliberate_signals_project_stable_weather(text: str, scene: WeatherScene) -> None:
    snapshot = RhythmEstimator().estimate("workspace-1", [checkin(text)], now=NOW)

    assert project_weather(snapshot, now=NOW).scene is scene


def test_high_switch_metadata_projects_fragmentation() -> None:
    signal = ActivityMetadata(
        observed_at=NOW,
        window_start=NOW - timedelta(minutes=10),
        window_end=NOW,
        active_seconds=540,
        idle_seconds=60,
        app_switch_count=35,
        category_seconds={AppCategory.DEVELOPMENT: 400, AppCategory.COMMUNICATION: 140},
    )
    snapshot = RhythmEstimator().estimate("workspace-1", [("event-1", signal)], now=NOW)

    assert project_weather(snapshot, now=NOW).scene is WeatherScene.FOG


def test_correction_outweighs_prior_hypothesis_without_mutating_fact() -> None:
    facts = [
        checkin("I am overloaded", "event-1"),
        (
            "event-2",
            CorrectionSignal(text="I am not overloaded; actually steady", observed_at=NOW),
        ),
    ]

    snapshot = RhythmEstimator().estimate("workspace-1", facts, now=NOW)

    assert project_weather(snapshot, now=NOW).scene is WeatherScene.FAIR
    assert "event-1" in snapshot.contradicting_event_ids
    assert "event-2" in snapshot.supporting_event_ids


def test_low_coverage_and_expired_state_project_mixed() -> None:
    empty = RhythmEstimator().estimate("workspace-1", [], now=NOW)
    old = RhythmEstimator().estimate(
        "workspace-1",
        [("event-1", CheckInSignal(text="I am in flow", observed_at=NOW - timedelta(hours=3)))],
        now=NOW,
    )

    assert project_weather(empty, now=NOW).scene is WeatherScene.MIXED
    assert project_weather(old, now=NOW).scene is WeatherScene.MIXED


def test_overload_policy_is_silent_and_reduces_interruption() -> None:
    snapshot = RhythmEstimator().estimate(
        "workspace-1", [checkin("I am overloaded and exhausted")], now=NOW
    )
    policy = project_policy(snapshot, now=NOW)

    assert policy.interaction_budget == "minimal"
    assert policy.response_density == "compact"
    assert policy.delegation_bias == "favor"
    assert policy.scope_pressure == "reduce"
    assert policy.proactivity == "silent"
