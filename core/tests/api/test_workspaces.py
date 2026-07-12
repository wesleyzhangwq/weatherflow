from pathlib import Path

from httpx import ASGITransport, AsyncClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings


async def test_workspace_api_authorizes_real_directory_idempotently(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    project = tmp_path / "project"
    project.mkdir()
    container = await RuntimeContainer.create(settings)
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/v1/workspaces",
            json={"name": "My project", "path": str(project)},
        )
        repeated = await client.post(
            "/v1/workspaces",
            json={"name": "Ignored retry", "path": str(project)},
        )
        listed = await client.get("/v1/workspaces")
        fetched = await client.get(f"/v1/workspaces/{first.json()['id']}")

    assert first.status_code == 201
    assert repeated.status_code == 201
    assert repeated.json()["id"] == first.json()["id"]
    assert first.json()["action_roots"] == [str(project.resolve())]
    assert first.json()["installed_packs"] == ["developer"]
    assert any(item["id"] == first.json()["id"] for item in listed.json())
    assert fetched.json()["action_roots"] == [str(project.resolve())]
    events = await container.ledger.list_stream("workspace", first.json()["id"])
    assert [event.type for event in events] == ["workspace.authorized"]


async def test_workspace_api_rejects_missing_directory(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path / "data"))
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/workspaces",
            json={"name": "Missing", "path": str(tmp_path / "missing")},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "workspace_path_invalid"


async def test_desktop_run_api_requires_an_explicit_authorized_workspace(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path / "data"))
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/v1/workspaces")
        response = await client.post(
            "/v1/runs",
            json={"client_request_id": "no-workspace", "user_intent": "Do work"},
        )

    assert listed.json() == []
    assert response.status_code == 422
