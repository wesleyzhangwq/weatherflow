from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from weatherflow.activity import (
    ActivityHeartbeat,
    ActivitySource,
    IdleState,
)


def test_macos_heartbeat_accepts_exact_window_metadata() -> None:
    heartbeat = ActivityHeartbeat(
        source=ActivitySource.MACOS_WINDOW,
        device_id="macbook",
        source_instance="native-main",
        source_event_id="native-1",
        observed_at=datetime(2026, 7, 16, 6, 0, tzinfo=UTC),
        pulsetime_seconds=15,
        app_name="Visual Studio Code",
        bundle_id="com.microsoft.VSCode",
        window_title="activity.rs — WeatherFlow",
        category="development",
        idle_state=IdleState.ACTIVE,
    )

    assert heartbeat.window_title == "activity.rs — WeatherFlow"
    assert heartbeat.state_payload()["app_name"] == "Visual Studio Code"
    assert "source_event_id" not in heartbeat.state_payload()


def test_browser_heartbeat_requires_complete_tab_identity() -> None:
    with pytest.raises(ValidationError):
        ActivityHeartbeat(
            source=ActivitySource.BROWSER_TAB,
            device_id="macbook",
            source_instance="chrome-extension",
            source_event_id="tab-1",
            observed_at=datetime(2026, 7, 16, 6, 0, tzinfo=UTC),
            pulsetime_seconds=80,
            browser_name="Chrome",
            tab_title="ActivityWatch",
            browser_window_id="window-1",
            browser_tab_id="tab-1",
        )


def test_browser_heartbeat_accepts_exact_tab_metadata() -> None:
    heartbeat = ActivityHeartbeat(
        source=ActivitySource.BROWSER_TAB,
        device_id="macbook",
        source_instance="chrome-extension",
        source_event_id="tab-1",
        observed_at=datetime(2026, 7, 16, 6, 0, tzinfo=UTC),
        pulsetime_seconds=80,
        browser_name="Chrome",
        browser_window_id="window-1",
        browser_tab_id="tab-1",
        url="https://github.com/ActivityWatch/activitywatch",
        domain="github.com",
        tab_title="ActivityWatch/activitywatch",
        audible=False,
        incognito=False,
        focused=True,
        idle_state=IdleState.ACTIVE,
        category="development",
    )

    assert heartbeat.state_payload()["browser_tab_id"] == "tab-1"


@pytest.mark.parametrize(
    "forbidden",
    ["screenshot", "keystrokes", "clipboard", "form_value", "cookie", "authorization"],
)
def test_activity_heartbeat_rejects_out_of_contract_content(forbidden: str) -> None:
    payload = {
        "source": "macos_window",
        "device_id": "macbook",
        "source_instance": "native-main",
        "source_event_id": "native-1",
        "observed_at": datetime(2026, 7, 16, 6, 0, tzinfo=UTC),
        "pulsetime_seconds": 15,
        "app_name": "Terminal",
        "bundle_id": "com.apple.Terminal",
        forbidden: "must-not-enter-activity",
    }

    with pytest.raises(ValidationError):
        ActivityHeartbeat.model_validate(payload)
