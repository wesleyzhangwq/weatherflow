from datetime import UTC, datetime, timedelta
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings


async def test_rhythm_signals_are_append_only_and_corrections_recompute(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))
    now = datetime.now(UTC)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        overloaded = await client.post(
            "/v1/rhythm/signals",
            json={"kind": "checkin", "text": "I am overloaded", "observed_at": now.isoformat()},
        )
        corrected = await client.post(
            "/v1/rhythm/signals",
            json={
                "kind": "correction",
                "text": "I am not overloaded; actually steady",
                "observed_at": (now + timedelta(seconds=1)).isoformat(),
            },
        )
        current = await client.get("/v1/rhythm/current")
        desktop = await client.get("/v1/desktop/snapshot")

    assert overloaded.status_code == 201
    assert overloaded.json()["weather"]["scene"] == "storm"
    assert corrected.json()["weather"]["scene"] == "fair"
    assert current.json() == corrected.json()
    assert desktop.json()["rhythm"] == corrected.json()
    events = await container.ledger.list_stream(
        "workspace", container.default_workspace.id, limit=1000
    )
    signal_events = [event for event in events if event.type.startswith("rhythm.signal.")]
    assert len(signal_events) == 2
    assert signal_events[0].id in corrected.json()["snapshot"]["contradicting_event_ids"]


async def test_rhythm_api_rejects_raw_activity_content(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))
    now = datetime.now(UTC)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/rhythm/signals",
            json={
                "kind": "activity_metadata",
                "observed_at": now.isoformat(),
                "window_start": (now - timedelta(minutes=5)).isoformat(),
                "window_end": now.isoformat(),
                "active_seconds": 240,
                "idle_seconds": 60,
                "app_switch_count": 4,
                "category_seconds": {"development": 240},
                "window_title": "secret document",
            },
        )

    assert response.status_code == 422
