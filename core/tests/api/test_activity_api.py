from datetime import UTC, datetime, timedelta
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from weatherflow.activity import ActivityHeartbeat, ActivityPreferences
from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings


async def test_activity_api_requires_opt_in_and_exposes_raw_and_summary_views(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))
    start = datetime(2026, 7, 16, 6, 0, tzinfo=UTC)
    heartbeat = {
        "source": "macos_window",
        "device_id": "macbook",
        "source_instance": "native-main",
        "source_event_id": "window-1",
        "observed_at": start.isoformat(),
        "pulsetime_seconds": 15,
        "app_name": "Terminal",
        "bundle_id": "com.apple.Terminal",
        "window_title": "zsh — WeatherFlow",
        "focused": True,
        "idle_state": "active",
        "category": "development",
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        defaults = await client.get("/v1/activity/preferences")
        rejected = await client.post("/v1/activity/heartbeats", json=heartbeat)
        enabled = await client.put(
            "/v1/activity/preferences",
            json={
                "expected_version": 0,
                "collection_enabled": True,
                "macos_enabled": True,
                "browser_enabled": False,
                "incognito_enabled": False,
                "remote_inference_enabled": False,
                "retention_days": 90,
            },
        )
        accepted = await client.post("/v1/activity/heartbeats", json=heartbeat)
        await client.post(
            "/v1/activity/heartbeats",
            json={
                **heartbeat,
                "source_event_id": "window-2",
                "observed_at": (start + timedelta(seconds=10)).isoformat(),
            },
        )
        raw = await client.get(
            "/v1/activity/events",
            params={
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=1)).isoformat(),
            },
        )
        summary = await client.get(
            "/v1/activity/summary",
            params={
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=1)).isoformat(),
            },
        )

    assert defaults.json()["collection_enabled"] is False
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "activity_collection_disabled"
    assert enabled.status_code == 200
    assert enabled.json()["version"] == 1
    assert accepted.status_code == 201
    assert raw.status_code == 200
    assert raw.json()[0]["window_title"] == "zsh — WeatherFlow"
    assert summary.json()["screen_seconds"] == 10
    assert summary.json()["app_switch_count"] == 0


async def test_activity_api_exports_and_deletes_only_after_confirmation(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    start = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    await container.activity.update_preferences(
        ActivityPreferences(collection_enabled=True, macos_enabled=True),
        expected_version=0,
    )
    stored = await container.activity.ingest(
        ActivityHeartbeat(
            source="macos_window",
            device_id="macbook",
            source_instance="native-main",
            source_event_id="window-1",
            observed_at=start,
            pulsetime_seconds=15,
            app_name="Terminal",
            bundle_id="com.apple.Terminal",
            window_title="private exact title",
            focused=True,
            idle_state="active",
        )
    )
    inference = await container.activity_inference_repository.claim(
        scheduled_for=start,
        window_start=start - timedelta(hours=1),
        workspace_id=container.default_workspace.id,
        now=start,
    )
    await container.activity_inference_repository.mark_executing(
        inference.id,
        provider="openai",
        model="gpt-test",
        event_ids=(stored.id,),
        redaction_count=1,
        request_payload="<untrusted_activity_data>\n[]\n</untrusted_activity_data>",
        now=start,
    )
    transport = ASGITransport(app=create_app(container=container))
    params = {
        "start": (start - timedelta(seconds=1)).isoformat(),
        "end": (start + timedelta(seconds=1)).isoformat(),
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        exported = await client.get("/v1/activity/export", params=params)
        history = await client.get("/v1/activity/inference/history")
        job_summaries = await client.get("/v1/activity/inference-jobs")
        job_detail = await client.get(f"/v1/activity/inference-jobs/{inference.id}")
        rejected = await client.request(
            "DELETE",
            "/v1/activity/events",
            params=params,
            json={"confirm": False},
        )
        deleted = await client.request(
            "DELETE",
            "/v1/activity/events",
            params=params,
            json={"confirm": True},
        )
        remaining = await client.get("/v1/activity/events", params=params)
        remaining_history = await client.get("/v1/activity/inference/history")

    assert exported.status_code == 200
    assert exported.json()["events"][0]["window_title"] == "private exact title"
    assert exported.json()["events"][0]["source_event_id"] == "window-1"
    assert exported.json()["preferences"]["collection_enabled"] is True
    assert history.json()[0]["request_payload"].startswith("<untrusted_activity_data>")
    assert job_summaries.json()[0]["request_payload"] is None
    assert job_detail.json()["request_payload"].startswith("<untrusted_activity_data>")
    assert history.json()[0]["redaction_count"] == 1
    assert rejected.status_code == 409
    assert deleted.json() == {"deleted": 1}
    assert remaining.json() == []
    assert remaining_history.json() == []


async def test_activity_api_reports_out_of_order_heartbeats_as_a_conflict(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    observed = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    await container.activity.update_preferences(
        ActivityPreferences(collection_enabled=True, macos_enabled=True),
        expected_version=0,
    )
    transport = ASGITransport(app=create_app(container=container))
    heartbeat = {
        "source": "macos_window",
        "device_id": "macbook",
        "source_instance": "native-main",
        "source_event_id": "newer",
        "observed_at": observed.isoformat(),
        "pulsetime_seconds": 15,
        "app_name": "Terminal",
        "bundle_id": "com.apple.Terminal",
        "window_title": "WeatherFlow",
        "focused": True,
        "idle_state": "active",
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post("/v1/activity/heartbeats", json=heartbeat)
        rejected = await client.post(
            "/v1/activity/heartbeats",
            json={
                **heartbeat,
                "source_event_id": "older",
                "observed_at": (observed - timedelta(seconds=1)).isoformat(),
            },
        )

    assert accepted.status_code == 201
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "activity_heartbeat_out_of_order"
