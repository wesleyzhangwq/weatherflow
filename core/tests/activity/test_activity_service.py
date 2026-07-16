from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from weatherflow.activity import (
    ActivityCollectionDisabledError,
    ActivityHeartbeat,
    ActivityPreferences,
    ActivityRepository,
    ActivityService,
    ActivitySource,
    IdleState,
)
from weatherflow.storage import Database


async def setup(tmp_path: Path) -> tuple[ActivityRepository, ActivityService]:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    repository = ActivityRepository(database)
    return repository, ActivityService(repository=repository)


def heartbeat(
    *,
    source: ActivitySource,
    event_id: str,
    observed_at: datetime,
    app_name: str | None = None,
    bundle_id: str | None = None,
    title: str | None = None,
    browser_window_id: str | None = None,
    browser_tab_id: str | None = None,
    url: str | None = None,
    tab_title: str | None = None,
) -> ActivityHeartbeat:
    return ActivityHeartbeat(
        source=source,
        device_id="macbook",
        source_instance=("native-main" if source is ActivitySource.MACOS_WINDOW else "chrome"),
        source_event_id=event_id,
        observed_at=observed_at,
        pulsetime_seconds=600,
        app_name=app_name,
        bundle_id=bundle_id,
        window_title=title,
        browser_name="Chrome" if source is ActivitySource.BROWSER_TAB else None,
        browser_window_id=browser_window_id,
        browser_tab_id=browser_tab_id,
        url=url,
        domain="github.com" if url else None,
        tab_title=tab_title,
        audible=False if source is ActivitySource.BROWSER_TAB else None,
        incognito=False if source is ActivitySource.BROWSER_TAB else None,
        focused=True,
        idle_state=IdleState.ACTIVE,
        category="development",
    )


async def test_collection_requires_source_specific_persisted_opt_in(tmp_path: Path) -> None:
    _, service = await setup(tmp_path)
    observed = datetime(2026, 7, 16, 6, 0, tzinfo=UTC)
    sample = heartbeat(
        source=ActivitySource.MACOS_WINDOW,
        event_id="native-1",
        observed_at=observed,
        app_name="Terminal",
        bundle_id="com.apple.Terminal",
        title="zsh",
    )

    with pytest.raises(ActivityCollectionDisabledError):
        await service.ingest(sample)

    await service.update_preferences(
        ActivityPreferences(collection_enabled=True, macos_enabled=True),
        expected_version=0,
    )
    stored = await service.ingest(sample)

    assert stored.app_name == "Terminal"


async def test_summary_counts_real_app_and_tab_switches_with_exact_rankings(
    tmp_path: Path,
) -> None:
    _, service = await setup(tmp_path)
    start = datetime(2026, 7, 16, 6, 0, tzinfo=UTC)
    await service.update_preferences(
        ActivityPreferences(
            collection_enabled=True,
            macos_enabled=True,
            browser_enabled=True,
        ),
        expected_version=0,
    )
    samples = [
        heartbeat(
            source=ActivitySource.MACOS_WINDOW,
            event_id="window-1",
            observed_at=start,
            app_name="Visual Studio Code",
            bundle_id="com.microsoft.VSCode",
            title="WeatherFlow",
        ),
        heartbeat(
            source=ActivitySource.BROWSER_TAB,
            event_id="tab-1",
            observed_at=start + timedelta(minutes=2),
            browser_window_id="window-1",
            browser_tab_id="tab-1",
            url="https://github.com/WeatherFlow",
            tab_title="WeatherFlow",
        ),
        heartbeat(
            source=ActivitySource.BROWSER_TAB,
            event_id="tab-2",
            observed_at=start + timedelta(minutes=5),
            browser_window_id="window-1",
            browser_tab_id="tab-2",
            url="https://github.com/ActivityWatch",
            tab_title="ActivityWatch",
        ),
        heartbeat(
            source=ActivitySource.BROWSER_TAB,
            event_id="tab-3",
            observed_at=start + timedelta(minutes=7),
            browser_window_id="window-1",
            browser_tab_id="tab-2",
            url="https://github.com/ActivityWatch",
            tab_title="ActivityWatch",
        ),
        heartbeat(
            source=ActivitySource.MACOS_WINDOW,
            event_id="window-keepalive",
            observed_at=start + timedelta(minutes=10),
            app_name="Visual Studio Code",
            bundle_id="com.microsoft.VSCode",
            title="WeatherFlow",
        ),
        heartbeat(
            source=ActivitySource.MACOS_WINDOW,
            event_id="window-2",
            observed_at=start + timedelta(minutes=15),
            app_name="Terminal",
            bundle_id="com.apple.Terminal",
            title="zsh",
        ),
        heartbeat(
            source=ActivitySource.MACOS_WINDOW,
            event_id="window-3",
            observed_at=start + timedelta(minutes=20),
            app_name="Terminal",
            bundle_id="com.apple.Terminal",
            title="zsh",
        ),
    ]
    for sample in samples:
        await service.ingest(sample)

    summary = await service.summary(start=start, end=start + timedelta(hours=1))

    assert summary.screen_seconds == 1_200
    assert summary.browser_seconds == 300
    assert summary.idle_seconds == 0
    assert summary.current_streak_seconds == 0
    assert summary.app_switch_count == 1
    assert summary.tab_switch_count == 1
    assert summary.top_apps[0].name == "Visual Studio Code"
    assert summary.top_apps[0].seconds == 900
    assert summary.top_domains[0].name == "github.com"
    assert summary.category_seconds == {"development": 1_200}


async def test_ingest_scrubs_credentials_before_raw_vault_write(tmp_path: Path) -> None:
    repository, service = await setup(tmp_path)
    observed = datetime(2026, 7, 16, 6, 0, tzinfo=UTC)
    await service.update_preferences(
        ActivityPreferences(collection_enabled=True, browser_enabled=True),
        expected_version=0,
    )
    sample = heartbeat(
        source=ActivitySource.BROWSER_TAB,
        event_id="tab-secret",
        observed_at=observed,
        browser_window_id="window-1",
        browser_tab_id="tab-1",
        url="https://alice:password@example.com/?code=oauth-secret&q=weather",
        tab_title="Token sk-proj-abcdefghijklmnopqrstuvwxyz123456",
    )

    stored = await service.ingest(sample)
    events = await repository.list_events(
        start=observed - timedelta(seconds=1),
        end=observed + timedelta(seconds=1),
    )

    assert stored.url == "https://example.com/?code=%5BREDACTED%5D&q=weather"
    assert stored.tab_title == "Token [REDACTED]"
    assert events == [stored]


async def test_retention_removes_expired_activity_when_configured(tmp_path: Path) -> None:
    repository, service = await setup(tmp_path)
    now = datetime(2026, 7, 16, 6, 0, tzinfo=UTC)
    await service.update_preferences(
        ActivityPreferences(
            collection_enabled=True,
            macos_enabled=True,
            retention_days=30,
        ),
        expected_version=0,
    )
    await service.ingest(
        heartbeat(
            source=ActivitySource.MACOS_WINDOW,
            event_id="expired",
            observed_at=now - timedelta(days=31),
            app_name="Terminal",
            bundle_id="com.apple.Terminal",
            title="old",
        )
    )
    await service.ingest(
        heartbeat(
            source=ActivitySource.MACOS_WINDOW,
            event_id="current",
            observed_at=now,
            app_name="Terminal",
            bundle_id="com.apple.Terminal",
            title="new",
        )
    )

    deleted = await service.apply_retention(now=now)

    assert deleted == 1
    assert [
        event.window_title
        for event in await repository.list_events(
            start=now - timedelta(days=32),
            end=now + timedelta(seconds=1),
        )
    ] == ["new"]
