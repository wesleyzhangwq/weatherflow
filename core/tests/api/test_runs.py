from pathlib import Path

from httpx import ASGITransport, AsyncClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings


async def test_run_api_is_idempotent_and_exposes_timeline(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    app = create_app(container=container)
    transport = ASGITransport(app=app)
    payload = {
        "client_request_id": "request-1",
        "user_intent": "Explain WeatherFlow",
        "execute": True,
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/v1/runs", json=payload)
        repeated = await client.post("/v1/runs", json=payload)
        run_id = first.json()["id"]
        fetched = await client.get(f"/v1/runs/{run_id}")
        timeline = await client.get(f"/v1/runs/{run_id}/timeline")

    assert first.status_code == 201
    assert repeated.status_code == 201
    assert repeated.json()["id"] == run_id
    assert fetched.json()["status"] == "succeeded"
    event_types = [event["type"] for event in timeline.json()]
    assert event_types[0] == "run.created"
    assert "run.result_committed" in event_types


async def test_run_api_returns_typed_not_found(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/runs/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "run_not_found", "run_id": "missing"}}
