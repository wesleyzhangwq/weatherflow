from datetime import UTC, datetime, timedelta
from pathlib import Path

from weatherflow.activity import (
    ActivityHeartbeat,
    ActivityPreferences,
    ActivityRepository,
    ActivitySource,
    IdleState,
)
from weatherflow.storage import Database


async def setup(tmp_path: Path) -> ActivityRepository:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    return ActivityRepository(database)


def window_heartbeat(
    *,
    event_id: str,
    observed_at: datetime,
    app_name: str = "Visual Studio Code",
    bundle_id: str = "com.microsoft.VSCode",
    title: str = "activity.rs — WeatherFlow",
) -> ActivityHeartbeat:
    return ActivityHeartbeat(
        source=ActivitySource.MACOS_WINDOW,
        device_id="macbook",
        source_instance="native-main",
        source_event_id=event_id,
        observed_at=observed_at,
        pulsetime_seconds=15,
        app_name=app_name,
        bundle_id=bundle_id,
        window_title=title,
        category="development",
        idle_state=IdleState.ACTIVE,
    )


async def test_preferences_are_disabled_until_explicitly_enabled(tmp_path: Path) -> None:
    repository = await setup(tmp_path)

    preferences = await repository.get_preferences()

    assert preferences == ActivityPreferences()
    assert preferences.collection_enabled is False
    assert preferences.remote_inference_enabled is False


async def test_heartbeat_extends_identical_state_and_transition_closes_it(
    tmp_path: Path,
) -> None:
    repository = await setup(tmp_path)
    started = datetime(2026, 7, 16, 6, 0, tzinfo=UTC)

    first = await repository.record_heartbeat(
        window_heartbeat(event_id="native-1", observed_at=started)
    )
    extended = await repository.record_heartbeat(
        window_heartbeat(event_id="native-2", observed_at=started + timedelta(seconds=10))
    )
    transitioned = await repository.record_heartbeat(
        window_heartbeat(
            event_id="native-3",
            observed_at=started + timedelta(seconds=15),
            app_name="Terminal",
            bundle_id="com.apple.Terminal",
            title="zsh",
        )
    )
    events = await repository.list_events(
        start=started,
        end=started + timedelta(minutes=1),
    )

    assert extended.id == first.id
    assert extended.duration_seconds == 10
    assert transitioned.id != first.id
    assert first.source_event_id == "native-1"
    assert transitioned.source_event_id == "native-3"
    assert [event.app_name for event in events] == ["Visual Studio Code", "Terminal"]
    assert events[0].ended_at == started + timedelta(seconds=15)
    assert events[0].duration_seconds == 15


async def test_source_event_retry_is_idempotent(tmp_path: Path) -> None:
    repository = await setup(tmp_path)
    observed = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)
    heartbeat = window_heartbeat(event_id="retry-me", observed_at=observed)

    first = await repository.record_heartbeat(heartbeat)
    retried = await repository.record_heartbeat(heartbeat)
    events = await repository.list_events(
        start=observed - timedelta(seconds=1),
        end=observed + timedelta(seconds=1),
    )

    assert retried == first
    assert events == [first]


async def test_delete_range_removes_only_overlapping_activity(tmp_path: Path) -> None:
    repository = await setup(tmp_path)
    morning = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    evening = datetime(2026, 7, 16, 18, 0, tzinfo=UTC)
    await repository.record_heartbeat(window_heartbeat(event_id="morning", observed_at=morning))
    await repository.record_heartbeat(window_heartbeat(event_id="evening", observed_at=evening))

    deleted = await repository.delete_range(
        start=morning - timedelta(minutes=1),
        end=morning + timedelta(minutes=1),
    )

    assert deleted == 1
    assert await repository.list_events(
        start=evening - timedelta(minutes=1),
        end=evening + timedelta(minutes=1),
    )


async def test_activity_queries_filter_exact_app_domain_category_and_source(
    tmp_path: Path,
) -> None:
    repository = await setup(tmp_path)
    observed = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    await repository.record_heartbeat(window_heartbeat(event_id="code", observed_at=observed))

    matching = await repository.list_events(
        start=observed - timedelta(seconds=1),
        end=observed + timedelta(seconds=1),
        source=ActivitySource.MACOS_WINDOW,
        app_name="Visual Studio Code",
        category="development",
    )
    wrong_app = await repository.list_events(
        start=observed - timedelta(seconds=1),
        end=observed + timedelta(seconds=1),
        app_name="Terminal",
    )
    wrong_domain = await repository.list_events(
        start=observed - timedelta(seconds=1),
        end=observed + timedelta(seconds=1),
        domain="github.com",
    )

    assert [event.source_event_id for event in matching] == ["code"]
    assert wrong_app == []
    assert wrong_domain == []
