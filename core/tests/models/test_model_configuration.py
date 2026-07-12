import json
from pathlib import Path

import httpx
import pytest

from weatherflow.events import EventLedger
from weatherflow.extensions import CredentialRef, KeyringCredentialStore
from weatherflow.models import (
    MiniMaxAdapter,
    MiniMaxAuthenticationError,
    ModelConfigurationRepository,
    ModelConfigurationService,
    ModelProvider,
    OpenAICompatibleAdapter,
    provider_presets,
)
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository

SECRET = "valid-minimax-key"


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password


class LockedKeyring(FakeKeyring):
    def get_password(self, service: str, username: str) -> str | None:
        raise RuntimeError("keychain is locked")


def model_transport(*, status: int = 200):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        if status != 200:
            return httpx.Response(status, json={"error": {"message": SECRET}})
        return httpx.Response(
            200,
            json={"data": [{"id": "MiniMax-M3"}, {"id": "deepseek-v4-flash"}]},
        )

    return httpx.MockTransport(handler)


async def setup(tmp_path: Path, backend: FakeKeyring, *, status: int = 200):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = Workspace.new(
        name="Model",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await WorkspaceRepository(database).create(workspace)
    ledger = EventLedger(database)
    store = KeyringCredentialStore(backend=backend)
    service = ModelConfigurationService(
        database=database,
        repository=ModelConfigurationRepository(database),
        ledger=ledger,
        credential_store=store,
        client=httpx.AsyncClient(transport=model_transport(status=status)),
    )
    return database, workspace, ledger, store, service


def test_keyring_store_resolves_by_reference_without_secret_repr() -> None:
    backend = FakeKeyring()
    store = KeyringCredentialStore(backend=backend)
    reference = CredentialRef(provider="minimax", name="api_key")

    store.set(reference, SECRET)

    assert store.resolve(reference) == SECRET
    assert SECRET not in repr(store)
    assert backend.values == {("ai.weatherflow.minimax", "api_key"): SECRET}


async def test_validated_minimax_configuration_persists_reference_only(
    tmp_path: Path,
) -> None:
    backend = FakeKeyring()
    database, workspace, ledger, store, service = await setup(tmp_path, backend)

    configuration = await service.configure_minimax(
        workspace_id=workspace.id,
        api_key=SECRET,
        model="MiniMax-M3",
        base_url="https://api.minimax.test/v1/",
    )

    assert configuration.provider is ModelProvider.MINIMAX
    assert configuration.base_url == "https://api.minimax.test/v1"
    assert configuration.credential_ref == CredentialRef(provider="minimax", name="api_key")
    assert isinstance(service.adapter(configuration), MiniMaxAdapter)
    assert store.resolve(configuration.credential_ref) == SECRET
    async with database.connect() as connection:
        rows = await (
            await connection.execute(
                "SELECT provider, model, base_url, credential_ref FROM model_configurations"
            )
        ).fetchall()
    durable = json.dumps([dict(row) for row in rows])
    assert SECRET not in durable
    events = await ledger.list_stream("workspace", workspace.id, limit=100)
    assert SECRET not in "".join(event.model_dump_json() for event in events)
    assert events[-1].type == "model.configuration_changed"


async def test_invalid_key_is_not_stored_or_activated(tmp_path: Path) -> None:
    backend = FakeKeyring()
    _, workspace, _, _, service = await setup(tmp_path, backend, status=401)

    with pytest.raises(MiniMaxAuthenticationError):
        await service.configure_minimax(
            workspace_id=workspace.id,
            api_key=SECRET,
            model="MiniMax-M3",
            base_url="https://api.minimax.test/v1",
        )

    assert backend.values == {}
    assert await service.repository.get(workspace.id) is None


def test_mainland_provider_presets_expose_editable_https_endpoints() -> None:
    presets = {preset.provider: preset for preset in provider_presets()}

    assert set(presets) == {
        ModelProvider.MINIMAX,
        ModelProvider.DEEPSEEK,
        ModelProvider.MOONSHOT,
        ModelProvider.QWEN,
        ModelProvider.ZHIPU,
        ModelProvider.SILICONFLOW,
        ModelProvider.STEPFUN,
    }
    assert presets[ModelProvider.DEEPSEEK].default_model == "deepseek-v4-flash"
    assert (
        presets[ModelProvider.QWEN].base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    assert all(preset.base_url.startswith("https://") for preset in presets.values())


async def test_generic_provider_configuration_uses_shared_compatible_adapter(
    tmp_path: Path,
) -> None:
    backend = FakeKeyring()
    database, workspace, ledger, store, service = await setup(tmp_path, backend)

    configuration = await service.configure(
        workspace_id=workspace.id,
        provider=ModelProvider.DEEPSEEK,
        api_key=SECRET,
        model="deepseek-v4-flash",
        base_url="https://api.minimax.test/v1",
    )

    assert configuration.provider is ModelProvider.DEEPSEEK
    assert isinstance(service.adapter(configuration), OpenAICompatibleAdapter)
    assert store.resolve(configuration.credential_ref) == SECRET
    events = await ledger.list_stream("workspace", workspace.id, limit=100)
    assert SECRET not in "".join(event.model_dump_json() for event in events)
    assert (await ModelConfigurationRepository(database).get(workspace.id)) == configuration


async def test_status_stays_available_when_keychain_access_is_denied(tmp_path: Path) -> None:
    backend = FakeKeyring()
    _, workspace, _, _, service = await setup(tmp_path, backend)
    await service.configure_minimax(
        workspace_id=workspace.id,
        api_key=SECRET,
        model="MiniMax-M3",
        base_url="https://api.minimax.test/v1",
    )
    service.credential_store = KeyringCredentialStore(backend=LockedKeyring())

    status = await service.status(workspace.id)

    assert status.configured is True
    assert status.credential_available is False
