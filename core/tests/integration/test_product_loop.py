import asyncio
import socket
from pathlib import Path

import httpx
import uvicorn

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.runtime import FinalTurn


class ProductLoopModel:
    async def complete(self, request):
        return FinalTurn(content="Inspected the authorized project without changing it.")


class ReadyServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config) -> None:
        super().__init__(config)
        self.ready = asyncio.Event()

    async def startup(self, sockets=None) -> None:
        await super().startup(sockets=sockets)
        self.ready.set()


async def test_real_http_bridge_runs_authorized_project_in_background(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    settings = Settings(data_dir=tmp_path / "data", bridge_token="integration-secret")
    container = await RuntimeContainer.create(settings, model=ProductLoopModel())
    app = create_app(settings, container=container)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = ReadyServer(uvicorn.Config(app, log_level="error", lifespan="off"))
    server_task = asyncio.create_task(server.serve(sockets=[listener]))
    await server.ready.wait()

    try:
        headers = {"Authorization": "Bearer integration-secret"}
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", headers=headers
        ) as client:
            workspace_response = await client.post(
                "/v1/workspaces",
                json={"name": "Real project", "path": str(project)},
            )
            workspace_id = workspace_response.json()["id"]
            accepted = await client.post(
                "/v1/runs",
                json={
                    "client_request_id": "real-http-loop",
                    "user_intent": "Inspect this project",
                    "workspace_id": workspace_id,
                },
            )
            run_id = accepted.json()["id"]
            completed = await container.wait_for_background_run(run_id, timeout_seconds=2)
            listed = await client.get("/v1/runs", params={"workspace_id": workspace_id})
            timeline = await client.get(f"/v1/runs/{run_id}/timeline")
            snapshot = await client.get(
                "/v1/desktop/snapshot", params={"workspace_id": workspace_id}
            )
    finally:
        server.should_exit = True
        await server_task

    assert workspace_response.status_code == 201
    assert accepted.status_code == 201
    assert completed.status.value == "succeeded"
    assert listed.json()[0]["result_summary"] == (
        "Inspected the authorized project without changing it."
    )
    assert any(event["type"] == "run.result_committed" for event in timeline.json())
    assert snapshot.json()["workspace"]["id"] == workspace_id
    assert container.background_tasks == {}
