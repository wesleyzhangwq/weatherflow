import asyncio
from pathlib import Path

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
    container.connector_sync_task.cancel()
    try:
        await container.connector_sync_task
    except asyncio.CancelledError:
        pass
