import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.runtime import FinalTurn


class GatedModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, request):
        self.started.set()
        await self.release.wait()
        return FinalTurn(content="Background result")


async def test_run_api_is_idempotent_and_exposes_timeline(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    app = create_app(container=container)
    transport = ASGITransport(app=app)
    payload = {
        "client_request_id": "request-1",
        "user_intent": "Explain WeatherFlow",
        "workspace_id": container.default_workspace.id,
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


async def test_desktop_run_acknowledges_before_background_model_completion(
    tmp_path: Path,
) -> None:
    model = GatedModel()
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path), model=model)
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/runs",
            json={
                "client_request_id": "background-1",
                "user_intent": "Inspect safely",
                "workspace_id": container.default_workspace.id,
            },
        )
        assert response.status_code == 201
        await asyncio.wait_for(model.started.wait(), timeout=1)
        stored = await container.runs.get(response.json()["id"])
        assert stored is not None and stored.status.value in {"planning", "running"}
        model.release.set()
        completed = await container.wait_for_background_run(stored.id, timeout_seconds=1)

    assert completed.status.value == "succeeded"
    final = await container.runs.get(stored.id)
    assert final is not None and final.result_summary == "Background result"


async def test_run_list_is_scoped_to_workspace(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))
    workspace_id = container.default_workspace.id
    await container.submit_run(
        user_intent="Queued",
        client_request_id="list-1",
        workspace_id=workspace_id,
        execute=False,
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/runs", params={"workspace_id": workspace_id})
        await container.wait_for_background_run(response.json()[0]["id"], timeout_seconds=1)

    assert response.status_code == 200
    assert [run["client_request_id"] for run in response.json()] == ["list-1"]


async def test_follow_up_run_keeps_durable_context_link(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    source, _ = await container.submit_run(
        user_intent="Produce a first result",
        client_request_id="source-run",
    )
    follow_up, _ = await container.submit_run(
        user_intent="Now make it more concise",
        client_request_id="follow-up-run",
        context_run_id=source.id,
        execute=False,
    )

    checkpoint = await container.checkpoints.get(follow_up.id)
    timeline = await container.ledger.list_correlation(follow_up.id, limit=1000)

    assert checkpoint is not None
    assert checkpoint.transcript[0].role.value == "system"
    assert source.id in checkpoint.transcript[0].content
    assert checkpoint.transcript[-1].content == "Now make it more concise"
    link = [event for event in timeline if event.type == "run.follow_up_linked"]
    assert len(link) == 1
    assert link[0].payload["context_run_id"] == source.id


async def test_cancel_stops_daemon_owned_background_run(tmp_path: Path) -> None:
    model = GatedModel()
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path), model=model)
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post(
            "/v1/runs",
            json={
                "client_request_id": "cancel-background",
                "user_intent": "Wait for cancellation",
                "workspace_id": container.default_workspace.id,
            },
        )
        await asyncio.wait_for(model.started.wait(), timeout=1)
        cancelled = await client.post(f"/v1/runs/{accepted.json()['id']}/cancel")

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert container.background_tasks == {}
