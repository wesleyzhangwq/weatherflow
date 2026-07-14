import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from weatherflow.events import EventLedger
from weatherflow.extensions import CredentialBroker, CredentialRef, KeyringCredentialStore
from weatherflow.models import (
    AnthropicMessagesAdapter,
    MiniMaxAdapter,
    MiniMaxAuthenticationError,
    ModelConfiguration,
    ModelConfigurationRepository,
    ModelConfigurationService,
    ModelProvider,
    OpenAICompatibleAdapter,
    OpenAIResponsesAdapter,
    ProviderModel,
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

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


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
            json={
                "data": [
                    {"id": "MiniMax-M3"},
                    {"id": "MiniMax-M2.7"},
                    {"id": "MiniMax-M2.7-highspeed"},
                    {"id": "MiniMax-M2.5"},
                    {"id": "MiniMax-M2.5-highspeed"},
                    {"id": "MiniMax-M2.1"},
                    {"id": "MiniMax-M2.1-highspeed"},
                    {"id": "MiniMax-M2"},
                    {"id": "deepseek-v4-flash"},
                    {"id": "retired-model"},
                ]
            },
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
    reference = CredentialRef(provider="minimax", name="api_key")
    store.set(reference, SECRET)

    configuration = await service.configure_minimax(
        workspace_id=workspace.id,
        model="MiniMax-M3",
        base_url="https://api.minimax.test/v1/",
    )

    assert configuration.provider is ModelProvider.MINIMAX
    assert configuration.base_url == "https://api.minimax.test/v1"
    assert configuration.credential_ref.provider == "minimax"
    assert configuration.credential_ref.name == "api_key"
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


async def test_invalid_key_is_not_activated_and_service_does_not_mutate_store(
    tmp_path: Path,
) -> None:
    backend = FakeKeyring()
    _, workspace, _, store, service = await setup(tmp_path, backend, status=401)
    store.set(CredentialRef(provider="minimax", name="api_key"), SECRET)

    with pytest.raises(MiniMaxAuthenticationError):
        await service.configure_minimax(
            workspace_id=workspace.id,
            model="MiniMax-M3",
            base_url="https://api.minimax.test/v1",
        )

    assert backend.values == {("ai.weatherflow.minimax", "api_key"): SECRET}
    assert await service.repository.get(workspace.id) is None


async def test_reconfiguration_keeps_fixed_reference_and_never_mutates_store(
    tmp_path: Path,
) -> None:
    backend = FakeKeyring()
    _, workspace, _, store, service = await setup(tmp_path, backend)
    reference = CredentialRef(provider="minimax", name="api_key")
    store.set(reference, SECRET)
    first = await service.configure_minimax(
        workspace_id=workspace.id,
        model="MiniMax-M3",
        base_url="https://api.minimax.test/v1",
    )

    second = await service.configure_minimax(
        workspace_id=workspace.id,
        model="MiniMax-M3",
        base_url="https://api.minimax.test/v1",
    )

    assert second.credential_ref == first.credential_ref == reference
    assert backend.values == {("ai.weatherflow.minimax", "api_key"): SECRET}


def test_mainland_provider_presets_expose_current_official_agent_models() -> None:
    presets = {preset.provider: preset for preset in provider_presets()}

    assert set(presets) == {
        ModelProvider.MINIMAX,
        ModelProvider.DEEPSEEK,
        ModelProvider.MOONSHOT,
        ModelProvider.QWEN,
        ModelProvider.ZHIPU,
        ModelProvider.SILICONFLOW,
        ModelProvider.STEPFUN,
        ModelProvider.OPENAI,
        ModelProvider.ANTHROPIC,
    }
    assert presets[ModelProvider.DEEPSEEK].default_model == "deepseek-v4-flash"
    assert presets[ModelProvider.MINIMAX].suggested_models[:3] == (
        "MiniMax-M3",
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
    )
    assert presets[ModelProvider.MINIMAX].suggested_models[-3:] == (
        "MiniMax-M2.1",
        "MiniMax-M2.1-highspeed",
        "MiniMax-M2",
    )
    assert presets[ModelProvider.MOONSHOT].suggested_models[:3] == (
        "kimi-k2.7-code",
        "kimi-k2.7-code-highspeed",
        "kimi-k2.6",
    )
    assert presets[ModelProvider.QWEN].suggested_models == (
        "qwen3.7-max",
        "qwen3.7-plus",
        "qwen3.6-flash",
    )
    assert presets[ModelProvider.ZHIPU].default_model == "glm-5.2"
    assert presets[ModelProvider.STEPFUN].suggested_models == (
        "step-3.7-flash",
        "step-3.5-flash-2603",
        "step-3.5-flash",
    )
    assert (
        presets[ModelProvider.QWEN].base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    assert all(preset.base_url.startswith("https://") for preset in presets.values())
    assert presets[ModelProvider.OPENAI].base_url == "https://api.openai.com/v1"
    assert presets[ModelProvider.OPENAI].suggested_models[:3] == (
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    )
    assert presets[ModelProvider.ANTHROPIC].base_url == "https://api.anthropic.com/v1"
    assert presets[ModelProvider.ANTHROPIC].suggested_models == (
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
    )


async def test_first_party_catalog_keeps_only_documented_maintained_models(
    tmp_path: Path,
) -> None:
    backend = FakeKeyring()
    _, _, _, store, service = await setup(tmp_path, backend)
    store.set(CredentialRef(provider="minimax", name="api_key"), SECRET)

    catalog = await service.available_models(ModelProvider.MINIMAX)

    assert catalog.provider is ModelProvider.MINIMAX
    assert catalog.source == "provider"
    assert catalog.models == (
        ProviderModel(id="MiniMax-M3"),
        ProviderModel(id="MiniMax-M2.7"),
        ProviderModel(id="MiniMax-M2.7-highspeed"),
        ProviderModel(id="MiniMax-M2.5"),
        ProviderModel(id="MiniMax-M2.5-highspeed"),
        ProviderModel(id="MiniMax-M2.1"),
        ProviderModel(id="MiniMax-M2.1-highspeed"),
        ProviderModel(id="MiniMax-M2"),
    )


async def test_siliconflow_catalog_uses_live_text_models_for_the_key(
    tmp_path: Path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.url.params.get("type") == "text"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "Qwen/Qwen3.5-32B"},
                    {"id": "deepseek-ai/DeepSeek-V4-Flash"},
                ]
            },
        )

    backend = FakeKeyring()
    _, _, _, store, service = await setup(tmp_path, backend)
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store.set(CredentialRef(provider="siliconflow", name="api_key"), SECRET)

    catalog = await service.available_models(ModelProvider.SILICONFLOW)

    assert catalog.models == (
        ProviderModel(id="Qwen/Qwen3.5-32B"),
        ProviderModel(id="deepseek-ai/DeepSeek-V4-Flash"),
    )


async def test_minimax_m2_models_are_selectable_with_continuation_support(
    tmp_path: Path,
) -> None:
    backend = FakeKeyring()
    _, workspace, _, store, service = await setup(tmp_path, backend)
    store.set(CredentialRef(provider="minimax", name="api_key"), SECRET)

    configured = await service.configure(
        workspace_id=workspace.id,
        provider=ModelProvider.MINIMAX,
        model="MiniMax-M2.7",
        base_url="https://api.minimax.test/v1",
    )

    assert configured.model == "MiniMax-M2.7"


async def test_generic_provider_configuration_uses_shared_compatible_adapter(
    tmp_path: Path,
) -> None:
    backend = FakeKeyring()
    database, workspace, ledger, store, service = await setup(tmp_path, backend)
    store.set(CredentialRef(provider="deepseek", name="api_key"), SECRET)

    configuration = await service.configure(
        workspace_id=workspace.id,
        provider=ModelProvider.DEEPSEEK,
        model="deepseek-v4-flash",
        base_url="https://api.minimax.test/v1",
    )

    assert configuration.provider is ModelProvider.DEEPSEEK
    assert isinstance(service.adapter(configuration), OpenAICompatibleAdapter)
    assert store.resolve(configuration.credential_ref) == SECRET
    events = await ledger.list_stream("workspace", workspace.id, limit=100)
    assert SECRET not in "".join(event.model_dump_json() for event in events)
    assert (await ModelConfigurationRepository(database).get(workspace.id)) == configuration


async def test_openai_and_anthropic_use_their_official_wire_adapters(tmp_path: Path) -> None:
    backend = FakeKeyring()
    _, workspace, _, store, service = await setup(tmp_path, backend)

    store.set(CredentialRef(provider="openai", name="api_key"), SECRET)
    openai = service._adapter(
        ModelConfiguration(
            workspace_id=workspace.id,
            provider=ModelProvider.OPENAI,
            model="gpt-5.6-terra",
            base_url="https://api.openai.com/v1",
            credential_ref=CredentialRef(provider="openai", name="api_key"),
            updated_at=datetime.now(UTC),
        ),
        CredentialBroker(store),
    )
    assert isinstance(openai, OpenAIResponsesAdapter)

    store.set(CredentialRef(provider="anthropic", name="api_key"), SECRET)
    anthropic = service._adapter(
        ModelConfiguration(
            workspace_id=workspace.id,
            provider=ModelProvider.ANTHROPIC,
            model="claude-sonnet-5",
            base_url="https://api.anthropic.com/v1",
            credential_ref=CredentialRef(provider="anthropic", name="api_key"),
            updated_at=datetime.now(UTC),
        ),
        CredentialBroker(store),
    )
    assert isinstance(anthropic, AnthropicMessagesAdapter)


async def test_status_stays_available_when_keychain_access_is_denied(tmp_path: Path) -> None:
    backend = FakeKeyring()
    _, workspace, _, store, service = await setup(tmp_path, backend)
    store.set(CredentialRef(provider="minimax", name="api_key"), SECRET)
    await service.configure_minimax(
        workspace_id=workspace.id,
        model="MiniMax-M3",
        base_url="https://api.minimax.test/v1",
    )
    service.credential_store = KeyringCredentialStore(backend=LockedKeyring())

    status = await service.status(workspace.id)

    assert status.configured is True
    assert status.credential_available is False
