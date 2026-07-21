import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlparse

import aiosqlite
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from weatherflow.events import Actor, Event, EventLedger
from weatherflow.extensions import (
    CredentialBroker,
    CredentialRef,
    CredentialStore,
)
from weatherflow.models.anthropic import AnthropicMessagesAdapter
from weatherflow.models.minimax import MiniMaxAdapter, OpenAICompatibleAdapter
from weatherflow.models.openai import OpenAIResponsesAdapter
from weatherflow.models.pricing import BillingOrigin
from weatherflow.runtime import ModelConfigurationRequiredError, ModelRouteUnavailableError
from weatherflow.storage import Database


class ModelProvider(StrEnum):
    MINIMAX = "minimax"
    DEEPSEEK = "deepseek"
    MOONSHOT = "moonshot"
    QWEN = "qwen"
    ZHIPU = "zhipu"
    SILICONFLOW = "siliconflow"
    STEPFUN = "stepfun"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class ProviderPreset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: ModelProvider
    label: str
    base_url: str
    default_model: str
    suggested_models: tuple[str, ...]
    billing_origins: tuple[BillingOrigin, ...] = ()


class ProviderModelCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: ModelProvider
    models: tuple["ProviderModel", ...]
    source: Literal["provider"] = "provider"


class ProviderModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    selectable: bool = True
    compatibility: Literal["agent_ready", "requires_hidden_reasoning"] = "agent_ready"
    note: str | None = None


def provider_presets() -> tuple[ProviderPreset, ...]:
    return (
        ProviderPreset(
            provider=ModelProvider.MINIMAX,
            label="MiniMax",
            base_url="https://api.minimaxi.com/v1",
            default_model="MiniMax-M3",
            suggested_models=(
                "MiniMax-M3",
                "MiniMax-M2.7",
                "MiniMax-M2.7-highspeed",
                "MiniMax-M2.5",
                "MiniMax-M2.5-highspeed",
                "MiniMax-M2.1",
                "MiniMax-M2.1-highspeed",
                "MiniMax-M2",
            ),
            billing_origins=tuple(BillingOrigin),
        ),
        ProviderPreset(
            provider=ModelProvider.DEEPSEEK,
            label="DeepSeek",
            base_url="https://api.deepseek.com",
            default_model="deepseek-v4-flash",
            suggested_models=("deepseek-v4-flash", "deepseek-v4-pro"),
        ),
        ProviderPreset(
            provider=ModelProvider.MOONSHOT,
            label="月之暗面 · Kimi",
            base_url="https://api.moonshot.cn/v1",
            default_model="kimi-k2.7-code",
            suggested_models=(
                "kimi-k2.7-code",
                "kimi-k2.7-code-highspeed",
                "kimi-k2.6",
                "kimi-k2.5",
                "moonshot-v1-8k",
                "moonshot-v1-32k",
                "moonshot-v1-128k",
            ),
        ),
        ProviderPreset(
            provider=ModelProvider.QWEN,
            label="阿里云百炼 · 千问",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            default_model="qwen3.7-plus",
            suggested_models=("qwen3.7-max", "qwen3.7-plus", "qwen3.6-flash"),
        ),
        ProviderPreset(
            provider=ModelProvider.ZHIPU,
            label="智谱 · GLM",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            default_model="glm-5.2",
            suggested_models=(
                "glm-5.2",
                "glm-5.1",
                "glm-5",
                "glm-5-turbo",
                "glm-4.7",
                "glm-4.7-flashx",
                "glm-4.7-flash",
                "glm-4.6",
                "glm-4.5-air",
                "glm-4.5-airx",
                "glm-4-long",
                "glm-4-flashx-250414",
                "glm-4-flash-250414",
            ),
        ),
        ProviderPreset(
            provider=ModelProvider.SILICONFLOW,
            label="硅基流动",
            base_url="https://api.siliconflow.cn/v1",
            default_model="deepseek-ai/DeepSeek-V4-Flash",
            suggested_models=(),
        ),
        ProviderPreset(
            provider=ModelProvider.STEPFUN,
            label="阶跃星辰",
            base_url="https://api.stepfun.com/v1",
            default_model="step-3.7-flash",
            suggested_models=(
                "step-3.7-flash",
                "step-3.5-flash-2603",
                "step-3.5-flash",
            ),
        ),
        ProviderPreset(
            provider=ModelProvider.OPENAI,
            label="OpenAI",
            base_url="https://api.openai.com/v1",
            default_model="gpt-5.6-terra",
            suggested_models=(
                "gpt-5.6-sol",
                "gpt-5.6-terra",
                "gpt-5.6-luna",
                "gpt-5.5",
                "gpt-5.5-pro",
                "gpt-5.4",
                "gpt-5.4-pro",
                "gpt-5.4-mini",
                "gpt-5.4-nano",
            ),
        ),
        ProviderPreset(
            provider=ModelProvider.ANTHROPIC,
            label="Anthropic",
            base_url="https://api.anthropic.com/v1",
            default_model="claude-sonnet-5",
            suggested_models=(
                "claude-fable-5",
                "claude-opus-4-8",
                "claude-sonnet-5",
                "claude-haiku-4-5-20251001",
            ),
        ),
    )


def normalize_model_base_url(value: str) -> str:
    normalized = value.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
        raise ValueError("model base URL must be an HTTPS origin/path without query")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("model base URL cannot contain credentials")
    return normalized


class ModelConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    workspace_id: str
    provider: ModelProvider
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=500)
    credential_ref: CredentialRef
    billing_origin: BillingOrigin | None = None
    version: int = Field(default=0, ge=0)
    updated_at: datetime

    @field_validator("base_url")
    @classmethod
    def valid_https_base_url(cls, value: str) -> str:
        return normalize_model_base_url(value)

    @model_validator(mode="after")
    def coherent_billing_origin(self) -> "ModelConfiguration":
        if self.provider is not ModelProvider.MINIMAX and self.billing_origin is not None:
            raise ValueError("billing_origin is supported only for MiniMax")
        return self


class ModelStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    configured: bool
    provider: str
    model: str | None = None
    base_url: str | None = None
    billing_origin: BillingOrigin | None = None
    credential_available: bool = False


class RunModelRoute(BaseModel):
    """Immutable provider/model selection captured when a Run is accepted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    workspace_id: str
    configuration_workspace_id: str | None = None
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    credential_ref: CredentialRef | None = None
    billing_origin: BillingOrigin | None = None
    configuration_version: int | None = Field(default=None, ge=0)
    bound_at: datetime

    @model_validator(mode="after")
    def coherent_route(self) -> "RunModelRoute":
        if self.provider == "echo":
            if any(
                value is not None
                for value in (
                    self.base_url,
                    self.credential_ref,
                    self.billing_origin,
                    self.configuration_version,
                    self.configuration_workspace_id,
                )
            ):
                raise ValueError("echo route cannot carry provider configuration")
            return self
        ModelProvider(self.provider)
        if self.provider != ModelProvider.MINIMAX.value and self.billing_origin is not None:
            raise ValueError("billing_origin is supported only for MiniMax")
        if (
            self.base_url is None
            or self.credential_ref is None
            or self.configuration_version is None
            or self.configuration_workspace_id is None
        ):
            raise ValueError("provider route requires a complete frozen configuration")
        return self


class ModelConfigurationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(self, workspace_id: str) -> ModelConfiguration | None:
        async with self.database.connect() as connection:
            return await self.get_in(connection, workspace_id)

    async def get_in(
        self, connection: aiosqlite.Connection, workspace_id: str
    ) -> ModelConfiguration | None:
        row = await (
            await connection.execute(
                "SELECT * FROM model_configurations WHERE workspace_id = ?",
                (workspace_id,),
            )
        ).fetchone()
        return _from_row(row) if row else None

    async def save_in(
        self,
        connection: aiosqlite.Connection,
        configuration: ModelConfiguration,
    ) -> ModelConfiguration:
        current = await self.get_in(connection, configuration.workspace_id)
        version = 0 if current is None else current.version + 1
        updated = configuration.model_copy(
            update={"version": version, "updated_at": datetime.now(UTC)}
        )
        await connection.execute(
            """
            INSERT INTO model_configurations(
                workspace_id, provider, model, base_url, credential_ref,
                billing_origin, version, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id) DO UPDATE SET
                provider = excluded.provider,
                model = excluded.model,
                base_url = excluded.base_url,
                credential_ref = excluded.credential_ref,
                billing_origin = excluded.billing_origin,
                version = excluded.version,
                updated_at = excluded.updated_at
            """,
            (
                updated.workspace_id,
                updated.provider.value,
                updated.model,
                updated.base_url,
                updated.credential_ref.model_dump_json(),
                updated.billing_origin.value if updated.billing_origin is not None else None,
                updated.version,
                updated.updated_at.isoformat(),
            ),
        )
        return updated


class RunModelRouteRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(self, run_id: str) -> RunModelRoute | None:
        async with self.database.connect() as connection:
            return await self.get_in(connection, run_id)

    async def get_in(
        self,
        connection: aiosqlite.Connection,
        run_id: str,
    ) -> RunModelRoute | None:
        row = await (
            await connection.execute(
                "SELECT * FROM run_model_routes WHERE run_id = ?",
                (run_id,),
            )
        ).fetchone()
        return _route_from_row(row) if row else None

    async def create_in(
        self,
        connection: aiosqlite.Connection,
        route: RunModelRoute,
    ) -> RunModelRoute:
        await connection.execute(
            """
            INSERT OR IGNORE INTO run_model_routes(
                run_id, workspace_id, configuration_workspace_id, provider,
                model, base_url, credential_ref, billing_origin,
                configuration_version, bound_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                route.run_id,
                route.workspace_id,
                route.configuration_workspace_id,
                route.provider,
                route.model,
                route.base_url,
                route.credential_ref.model_dump_json() if route.credential_ref else None,
                route.billing_origin.value if route.billing_origin is not None else None,
                route.configuration_version,
                route.bound_at.isoformat(),
            ),
        )
        stored = await self.get_in(connection, route.run_id)
        if stored is None:
            raise RuntimeError(route.run_id)
        return stored


class ModelConfigurationService:
    def __init__(
        self,
        *,
        database: Database,
        repository: ModelConfigurationRepository,
        ledger: EventLedger,
        credential_store: CredentialStore,
        client: httpx.AsyncClient | None = None,
        routes: RunModelRouteRepository | None = None,
    ) -> None:
        self.database = database
        self.repository = repository
        self.ledger = ledger
        self.credential_store = credential_store
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient()
        self.routes = routes or RunModelRouteRepository(database)

    async def close(self) -> None:
        if self._owns_client and not self.client.is_closed:
            await self.client.aclose()

    async def configure_minimax(
        self,
        *,
        workspace_id: str,
        model: str,
        base_url: str,
        billing_origin: BillingOrigin | None = None,
    ) -> ModelConfiguration:
        return await self.configure(
            workspace_id=workspace_id,
            provider=ModelProvider.MINIMAX,
            model=model,
            base_url=base_url,
            billing_origin=billing_origin,
        )

    async def configure(
        self,
        *,
        workspace_id: str,
        provider: ModelProvider,
        model: str,
        base_url: str,
        billing_origin: BillingOrigin | None = None,
    ) -> ModelConfiguration:
        reference = CredentialRef(provider=provider.value, name="api_key")
        candidate = ModelConfiguration(
            workspace_id=workspace_id,
            provider=provider,
            model=model,
            base_url=base_url,
            credential_ref=reference,
            billing_origin=billing_origin,
            updated_at=datetime.now(UTC),
        )
        await self._adapter(candidate, CredentialBroker(self.credential_store)).verify()
        async with self.database.transaction() as connection:
            saved = await self.repository.save_in(connection, candidate)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="model.configuration_changed",
                    actor=Actor.USER,
                    stream_kind="workspace",
                    stream_id=workspace_id,
                    correlation_id=workspace_id,
                    payload={
                        "provider": saved.provider.value,
                        "model": saved.model,
                        "base_url": saved.base_url,
                        "credential_ref": saved.credential_ref.model_dump(mode="json"),
                        "billing_origin": (
                            saved.billing_origin.value if saved.billing_origin is not None else None
                        ),
                        "version": saved.version,
                    },
                ),
            )
        return saved

    def adapter(
        self, configuration: ModelConfiguration
    ) -> OpenAICompatibleAdapter | OpenAIResponsesAdapter | AnthropicMessagesAdapter:
        return self._adapter(configuration, CredentialBroker(self.credential_store))

    async def bind_run(
        self,
        *,
        run_id: str,
        workspace_id: str,
    ) -> RunModelRoute:
        configuration = await self.repository.get(workspace_id)
        configuration_workspace_id = workspace_id if configuration is not None else None
        route = (
            RunModelRoute(
                run_id=run_id,
                workspace_id=workspace_id,
                configuration_workspace_id=configuration_workspace_id,
                provider=configuration.provider.value,
                model=configuration.model,
                base_url=configuration.base_url,
                credential_ref=configuration.credential_ref,
                billing_origin=configuration.billing_origin,
                configuration_version=configuration.version,
                bound_at=datetime.now(UTC),
            )
            if configuration is not None
            else RunModelRoute(
                run_id=run_id,
                workspace_id=workspace_id,
                provider="echo",
                model="echo",
                bound_at=datetime.now(UTC),
            )
        )
        async with self.database.transaction() as connection:
            existing = await self.routes.get_in(connection, run_id)
            if existing is not None:
                return existing
            stored = await self.routes.create_in(connection, route)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="model.route_bound",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=run_id,
                    correlation_id=run_id,
                    payload={
                        "provider": stored.provider,
                        "model": stored.model,
                        "configuration_version": stored.configuration_version,
                        "billing_origin": (
                            stored.billing_origin.value
                            if stored.billing_origin is not None
                            else None
                        ),
                    },
                ),
            )
        return stored

    async def clone_run_route(
        self,
        *,
        parent_run_id: str,
        child_run_id: str,
        workspace_id: str,
    ) -> RunModelRoute:
        parent = await self.routes.get(parent_run_id)
        if parent is None:
            raise ModelRouteUnavailableError(parent_run_id)
        route = parent.model_copy(
            update={
                "run_id": child_run_id,
                "workspace_id": workspace_id,
                "bound_at": datetime.now(UTC),
            }
        )
        async with self.database.transaction() as connection:
            existing = await self.routes.get_in(connection, child_run_id)
            if existing is not None:
                return existing
            stored = await self.routes.create_in(connection, route)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="model.route_bound",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=child_run_id,
                    correlation_id=child_run_id,
                    payload={
                        "provider": stored.provider,
                        "model": stored.model,
                        "configuration_version": stored.configuration_version,
                        "billing_origin": (
                            stored.billing_origin.value
                            if stored.billing_origin is not None
                            else None
                        ),
                    },
                ),
            )
        return stored

    async def resolve(
        self, run_id: str
    ) -> OpenAICompatibleAdapter | OpenAIResponsesAdapter | AnthropicMessagesAdapter | None:
        try:
            route = await self.routes.get(run_id)
            if route is None:
                raise ModelRouteUnavailableError(run_id)
            if route.provider == "echo":
                raise ModelConfigurationRequiredError(run_id)
            if route.base_url is None or route.credential_ref is None:
                raise ModelRouteUnavailableError(run_id)
            return self.adapter(
                ModelConfiguration(
                    workspace_id=route.workspace_id,
                    provider=ModelProvider(route.provider),
                    model=route.model,
                    base_url=route.base_url,
                    credential_ref=route.credential_ref,
                    billing_origin=route.billing_origin,
                    version=route.configuration_version or 0,
                    updated_at=route.bound_at,
                )
            )
        except ModelRouteUnavailableError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ModelRouteUnavailableError(run_id) from error

    async def available_models(
        self,
        provider: ModelProvider,
    ) -> ProviderModelCatalog:
        preset = next(item for item in provider_presets() if item.provider is provider)
        candidate = ModelConfiguration(
            workspace_id="catalog",
            provider=provider,
            model=preset.default_model,
            base_url=preset.base_url,
            credential_ref=CredentialRef(provider=provider.value, name="api_key"),
            updated_at=datetime.now(UTC),
        )
        query = {"type": "text"} if provider is ModelProvider.SILICONFLOW else None
        available = await self._adapter(
            candidate,
            CredentialBroker(self.credential_store),
        ).list_models(query=query)
        if provider is ModelProvider.SILICONFLOW:
            model_ids = available
        else:
            available_set = set(available)
            model_ids = tuple(model for model in preset.suggested_models if model in available_set)
        if not model_ids:
            raise ValueError("provider returned no supported language models")
        return ProviderModelCatalog(
            provider=provider,
            models=tuple(_provider_model(provider, model) for model in model_ids),
        )

    def _adapter(
        self,
        configuration: ModelConfiguration,
        broker: CredentialBroker,
    ) -> OpenAICompatibleAdapter | OpenAIResponsesAdapter | AnthropicMessagesAdapter:
        arguments = {
            "broker": broker,
            "credential_ref": configuration.credential_ref,
            "model": configuration.model,
            "base_url": configuration.base_url,
            "client": self.client,
        }
        if configuration.provider is ModelProvider.MINIMAX:
            return MiniMaxAdapter(
                **arguments,
                billing_origin=configuration.billing_origin,
            )
        if configuration.provider is ModelProvider.OPENAI:
            return OpenAIResponsesAdapter(**arguments)
        if configuration.provider is ModelProvider.ANTHROPIC:
            return AnthropicMessagesAdapter(**arguments)
        return OpenAICompatibleAdapter(provider=configuration.provider.value, **arguments)

    async def status(self, workspace_id: str) -> ModelStatus:
        configuration = await self.repository.get(workspace_id)
        if configuration is None:
            return ModelStatus(configured=False, provider="echo")
        try:
            presence_check = getattr(self.credential_store, "available", None)
            credential_available = (
                presence_check(configuration.credential_ref)
                if callable(presence_check)
                else self.credential_store.resolve(configuration.credential_ref) is not None
            )
        except Exception:
            # Keychain can be temporarily locked or deny a non-interactive lookup.
            # Status reads must remain available and never expose backend details.
            credential_available = False
        return ModelStatus(
            configured=True,
            provider=configuration.provider.value,
            model=configuration.model,
            base_url=configuration.base_url,
            billing_origin=configuration.billing_origin,
            credential_available=credential_available,
        )


def _from_row(row: Any) -> ModelConfiguration:
    return ModelConfiguration.model_validate(
        {
            "workspace_id": row["workspace_id"],
            "provider": row["provider"],
            "model": row["model"],
            "base_url": row["base_url"],
            "credential_ref": json.loads(row["credential_ref"]),
            "billing_origin": row["billing_origin"],
            "version": row["version"],
            "updated_at": row["updated_at"],
        }
    )


def _route_from_row(row: Any) -> RunModelRoute:
    return RunModelRoute.model_validate(
        {
            "run_id": row["run_id"],
            "workspace_id": row["workspace_id"],
            "configuration_workspace_id": row["configuration_workspace_id"],
            "provider": row["provider"],
            "model": row["model"],
            "base_url": row["base_url"],
            "credential_ref": (
                json.loads(row["credential_ref"]) if row["credential_ref"] else None
            ),
            "billing_origin": row["billing_origin"],
            "configuration_version": row["configuration_version"],
            "bound_at": row["bound_at"],
        }
    )


def _provider_model(provider: ModelProvider, model: str) -> ProviderModel:
    del provider
    return ProviderModel(id=model)
