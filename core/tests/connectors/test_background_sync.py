import asyncio
from pathlib import Path

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.extensions import MappingCredentialStore


class UnusedGateway:
    pass


async def test_existing_composio_key_restarts_auto_fetch_with_the_daemon(
    tmp_path: Path, monkeypatch
) -> None:
    store = MappingCredentialStore(
        {
            "composio.project_api_key": "local-secret",
            "provider_continuations.encryption_key_v1": "a" * 64,
        }
    )
    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path),
        credential_store=store,  # type: ignore[arg-type]
        connector_gateway=UnusedGateway(),  # type: ignore[arg-type]
    )
    called = asyncio.Event()

    async def sync_due():
        called.set()
        return []

    monkeypatch.setattr(container.connector_sync, "sync_due", sync_due)

    await container.start_background()
    await asyncio.wait_for(called.wait(), timeout=1)

    assert container.connector_sync_task is not None
    await container.stop_background()

    assert container.connector_sync_task is None


async def test_app_lifespan_awaits_connector_sync_shutdown(tmp_path: Path, monkeypatch) -> None:
    store = MappingCredentialStore(
        {
            "composio.project_api_key": "local-secret",
            "provider_continuations.encryption_key_v1": "a" * 64,
        }
    )
    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path),
        credential_store=store,  # type: ignore[arg-type]
        connector_gateway=UnusedGateway(),  # type: ignore[arg-type]
    )
    entered = asyncio.Event()
    exited = asyncio.Event()

    async def sync_due():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    monkeypatch.setattr(container.connector_sync, "sync_due", sync_due)
    app = create_app(container=container)

    async with app.router.lifespan_context(app):
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert container.connector_sync_task is not None

    assert exited.is_set()
    assert container.connector_sync_task is None
