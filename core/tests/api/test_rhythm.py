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

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "activity_metadata_ingest_forbidden"


async def test_activity_metadata_ingest_is_always_forbidden(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))
    now = datetime.now(UTC)
    payload = {
        "kind": "activity_metadata",
        "observed_at": now.isoformat(),
        "window_start": (now - timedelta(minutes=1)).isoformat(),
        "window_end": now.isoformat(),
        "active_seconds": 45,
        "idle_seconds": 15,
        "app_switch_count": 2,
        "category_seconds": {"development": 45},
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        rejected_before_onboarding = await client.post("/v1/rhythm/signals", json=payload)
        onboarding = await client.post(
            "/v1/onboarding/complete",
            json={
                "confirm_local_ownership": True,
            },
        )
        rejected_after_onboarding = await client.post("/v1/rhythm/signals", json=payload)

    assert onboarding.status_code == 200
    for response in (rejected_before_onboarding, rejected_after_onboarding):
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "activity_metadata_ingest_forbidden"
    events = await container.ledger.list_stream(
        "workspace", container.default_workspace.id, limit=1000
    )
    assert all(event.type != "rhythm.signal.activity_metadata" for event in events)


async def test_rhythm_insights_keep_deliberate_text_private_and_show_task_behavior(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))
    now = datetime.now(UTC)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/v1/rhythm/signals",
            json={
                "kind": "checkin",
                "text": "private deliberate state text must not appear in behavior history",
                "observed_at": (now - timedelta(minutes=6)).isoformat(),
            },
        )
        task_rhythm = await container.rhythm.record_task_behavior(
            workspace_id=container.default_workspace.id,
            run_id="run-rhythm-insight",
            outcome="succeeded",
            observed_at=now,
            duration_seconds=240,
            step_count=4,
        )

        events = await container.ledger.list_stream(
            "workspace", container.default_workspace.id, limit=1000
        )
        task_event = next(event for event in events if event.type == "rhythm.signal.task_behavior")
        assertion = await container.memory.create_assertion(
            workspace_id=container.default_workspace.id,
            claim="长时间专注后更适合先安排短暂恢复。",
            confidence=0.82,
            evidence_event_ids=(task_event.id,),
            origin="derived",
        )

        response = await client.get("/v1/rhythm/insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["current"]["snapshot"]["id"] == task_rhythm.snapshot.id
    assert payload["recent_behaviors"] == [
        {
            "id": task_event.id,
            "kind": "task",
            "observed_at": now.isoformat().replace("+00:00", "Z"),
            "active_minutes": None,
            "idle_minutes": None,
            "app_switch_count": None,
            "dominant_category": None,
            "outcome": "succeeded",
            "duration_minutes": 4,
            "step_count": 4,
        }
    ]
    assert payload["profile"] == [
        {
            "id": assertion.id,
            "claim": assertion.claim,
            "confidence": assertion.confidence,
            "origin": assertion.origin,
            "evidence_count": 1,
            "updated_at": assertion.updated_at.isoformat().replace("+00:00", "Z"),
        }
    ]
    assert "private deliberate state text" not in response.text
