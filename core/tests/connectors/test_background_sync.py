import asyncio
from pathlib import Path

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.extensions import (
    CredentialRef,
    CredentialUnavailableError,
    MappingCredentialStore,
)


class LockableCredentialStore:
    def __init__(self) -> None:
        self.locked = True

    def resolve(self, reference: CredentialRef) -> str | None:
        if reference.key != "composio.project_api_key":
            return None
        if self.locked:
            raise CredentialUnavailableError(reference.key)
        return "local-secret"

    def available(self, reference: CredentialRef) -> bool:
        return self.resolve(reference) is not None


class UnusedGateway:
    async def validate_api_key(self, api_key: str) -> None:
        assert api_key == "local-secret"


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


async def test_locked_keychain_at_start_keeps_retry_loop_alive_until_unlock(
    tmp_path: Path, monkeypatch
) -> None:
    store = LockableCredentialStore()
    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path),
        credential_store=store,
        connector_gateway=UnusedGateway(),  # type: ignore[arg-type]
        provider_continuation_key=bytes(range(32)),
    )
    synced = asyncio.Event()
    retry = asyncio.Event()
    original_sleep = asyncio.sleep

    async def sync_due():
        synced.set()
        return []

    async def wait_for_unlock(_seconds: float) -> None:
        await retry.wait()
        await original_sleep(0)

    monkeypatch.setattr(container.connector_sync, "sync_due", sync_due)
    monkeypatch.setattr("weatherflow.bootstrap.asyncio.sleep", wait_for_unlock)

    await container.start_background(
        include_automation_scheduler=False,
        include_activity_scheduler=False,
    )
    assert container.connector_sync_task is not None

    store.locked = False
    retry.set()
    await asyncio.wait_for(synced.wait(), timeout=1)
    await container.stop_background()


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


async def test_connector_background_loop_survives_one_unexpected_failure(
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
    recovered = asyncio.Event()
    calls = 0

    async def sync_due():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient repository failure")
        recovered.set()
        await asyncio.Event().wait()

    async def no_delay(_seconds: float) -> None:
        return None

    monkeypatch.setattr(container.connector_sync, "sync_due", sync_due)
    monkeypatch.setattr("weatherflow.bootstrap.asyncio.sleep", no_delay)

    container.start_connector_background()
    await asyncio.wait_for(recovered.wait(), timeout=1)
    await container.stop_background()

    assert calls == 2


async def test_repeated_runtime_start_retries_unfinished_connector_reconciliation(
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
    reconcile_calls = 0

    async def reconcile_configuration() -> bool:
        nonlocal reconcile_calls
        reconcile_calls += 1
        return reconcile_calls > 1

    async def sync_due():
        return []

    monkeypatch.setattr(
        container.connector_service,
        "reconcile_configuration",
        reconcile_configuration,
    )
    monkeypatch.setattr(container.connector_sync, "sync_due", sync_due)

    await container.start_background()
    await container.start_background()
    await container.stop_background()

    assert reconcile_calls == 2
