from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from weatherflow.rhythm import (
    ActivityMetadata,
    AppCategory,
    CheckInSignal,
    DimensionEstimate,
    DimensionName,
    Freshness,
    HumanStateSnapshot,
    RhythmPolicy,
    RhythmSignal,
    Trend,
    WeatherPresentation,
    WeatherScene,
)


@pytest.mark.parametrize("forbidden", ["screenshot", "window_title", "keystrokes", "clipboard"])
def test_activity_metadata_rejects_raw_content_fields(forbidden: str) -> None:
    payload = {
        "kind": "activity_metadata",
        "observed_at": datetime.now(UTC),
        "window_start": datetime.now(UTC) - timedelta(minutes=5),
        "window_end": datetime.now(UTC),
        "active_seconds": 240,
        "idle_seconds": 60,
        "app_switch_count": 4,
        "category_seconds": {"development": 200, "communication": 40},
        forbidden: "secret",
    }

    with pytest.raises(ValidationError):
        TypeAdapter(RhythmSignal).validate_python(payload)


def test_signal_union_accepts_deliberate_and_metadata_inputs() -> None:
    checkin = TypeAdapter(RhythmSignal).validate_python(
        {"kind": "checkin", "text": "I feel overloaded", "observed_at": datetime.now(UTC)}
    )
    activity = ActivityMetadata(
        observed_at=datetime.now(UTC),
        window_start=datetime.now(UTC) - timedelta(minutes=5),
        window_end=datetime.now(UTC),
        active_seconds=240,
        idle_seconds=60,
        app_switch_count=4,
        category_seconds={AppCategory.DEVELOPMENT: 240},
    )

    assert isinstance(checkin, CheckInSignal)
    assert activity.kind == "activity_metadata"


def test_snapshot_policy_and_weather_round_trip() -> None:
    now = datetime.now(UTC)
    dimensions = {
        name: DimensionEstimate(
            value=0.5,
            confidence=0.8,
            trend=Trend.STEADY,
            supporting_event_ids=("event-1",),
            contradicting_event_ids=(),
            freshness=Freshness.FRESH,
        )
        for name in DimensionName
    }
    snapshot = HumanStateSnapshot.new(
        workspace_id="workspace-1",
        observed_at=now,
        window_start=now - timedelta(hours=1),
        window_end=now,
        dimensions=dimensions,
        summary="Steady",
        supporting_event_ids=("event-1",),
        contradicting_event_ids=(),
        valid_until=now + timedelta(minutes=30),
    )
    policy = RhythmPolicy.from_snapshot(snapshot)
    weather = WeatherPresentation(
        scene=WeatherScene.FAIR,
        intensity=0.5,
        transition="steady",
        snapshot_id=snapshot.id,
        valid_until=snapshot.valid_until,
    )

    assert HumanStateSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot
    assert policy.proactivity == "silent"
    assert set(WeatherScene) == {
        WeatherScene.CLEAR,
        WeatherScene.FAIR,
        WeatherScene.FOG,
        WeatherScene.STORM,
        WeatherScene.STILL,
        WeatherScene.NIGHT,
        WeatherScene.MIXED,
    }
    assert WeatherPresentation.model_validate_json(weather.model_dump_json()) == weather
