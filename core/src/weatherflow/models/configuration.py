import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

import aiosqlite
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from weatherflow.events import Actor, Event, EventLedger
from weatherflow.extensions import (
    CredentialBroker,
    CredentialRef,
    MappingCredentialStore,
    WritableCredentialStore,
)
from weatherflow.models.minimax import MiniMaxAdapter, OpenAICompatibleAdapter
from weatherflow.storage import Database


class ModelProvider(StrEnum):
    MINIMAX = "minimax"
    DEEPSEEK = "deepseek"
    MOONSHOT = "moonshot"
    QWEN = "qwen"
    ZHIPU = "zhipu"
    SILICONFLOW = "siliconflow"
    STEPFUN = "stepfun"


class ProviderPreset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: ModelProvider
    label: str
    base_url: str
    default_model: str
    suggested_models: tuple[str, ...]


def provider_presets() -> tuple[ProviderPreset, ...]:
    return (
        ProviderPreset(
            provider=ModelProvider.MINIMAX,
            label="MiniMax",
            base_url="https://api.minimaxi.com/v1",
            default_model="MiniMax-M3",
            suggested_models=("MiniMax-M3",),
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
            default_model="kimi-k2.5",
            suggested_models=("kimi-k2.5",),
        ),
        ProviderPreset(
            provider=ModelProvider.QWEN,
            label="阿里云百炼 · 千问",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            default_model="qwen3.6-plus",
            suggested_models=("qwen3.6-plus", "qwen3.6-flash"),
        ),
        ProviderPreset(
            provider=ModelProvider.ZHIPU,
            label="智谱 · GLM",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            default_model="glm-5.1",
            suggested_models=("glm-5.1", "glm-5-flash"),
        ),
        ProviderPreset(
            provider=ModelProvider.SILICONFLOW,
            label="硅基流动",
            base_url="https://api.siliconflow.cn/v1",
            default_model="deepseek-ai/DeepSeek-V4-Flash",
            suggested_models=("deepseek-ai/DeepSeek-V4-Flash",),
        ),
        ProviderPreset(
            provider=ModelProvider.STEPFUN,
            label="阶跃星辰",
            base_url="https://api.stepfun.com/v1",
            default_model="step-3.5-flash",
            suggested_models=("step-3.5-flash",),
        ),
    )


class ModelConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    provider: ModelProvider
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=500)
    credential_ref: CredentialRef
    version: int = Field(default=0, ge=0)
    updated_at: datetime

    @field_validator("base_url")
    @classmethod
    def valid_https_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("model base URL must be an HTTPS origin/path without query")
        return normalized


class ModelStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    configured: bool
    provider: str
    model: str | None = None
    base_url: str | None = None
    credential_available: bool = False


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
                version, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id) DO UPDATE SET
                provider = excluded.provider,
                model = excluded.model,
                base_url = excluded.base_url,
                credential_ref = excluded.credential_ref,
                version = excluded.version,
                updated_at = excluded.updated_at
            """,
            (
                updated.workspace_id,
                updated.provider.value,
                updated.model,
                updated.base_url,
                updated.credential_ref.model_dump_json(),
                updated.version,
                updated.updated_at.isoformat(),
            ),
        )
        return updated


class ModelConfigurationService:
    def __init__(
        self,
        *,
        database: Database,
        repository: ModelConfigurationRepository,
        ledger: EventLedger,
        credential_store: WritableCredentialStore,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.database = database
        self.repository = repository
        self.ledger = ledger
        self.credential_store = credential_store
        self.client = client

    async def configure_minimax(
        self,
        *,
        workspace_id: str,
        api_key: str,
        model: str,
        base_url: str,
    ) -> ModelConfiguration:
        return await self.configure(
            workspace_id=workspace_id,
            provider=ModelProvider.MINIMAX,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )

    async def configure(
        self,
        *,
        workspace_id: str,
        provider: ModelProvider,
        api_key: str,
        model: str,
        base_url: str,
    ) -> ModelConfiguration:
        reference = CredentialRef(provider=provider.value, name="api_key")
        candidate = ModelConfiguration(
            workspace_id=workspace_id,
            provider=provider,
            model=model,
            base_url=base_url,
            credential_ref=reference,
            updated_at=datetime.now(UTC),
        )
        verifier = self._adapter(
            candidate,
            CredentialBroker(MappingCredentialStore({reference.key: api_key})),
        )
        await verifier.verify()
        self.credential_store.set(reference, api_key)
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
                        "version": saved.version,
                    },
                ),
            )
        return saved

    def adapter(self, configuration: ModelConfiguration) -> OpenAICompatibleAdapter:
        return self._adapter(configuration, CredentialBroker(self.credential_store))

    def _adapter(
        self,
        configuration: ModelConfiguration,
        broker: CredentialBroker,
    ) -> OpenAICompatibleAdapter:
        arguments = {
            "broker": broker,
            "credential_ref": configuration.credential_ref,
            "model": configuration.model,
            "base_url": configuration.base_url,
            "client": self.client,
        }
        if configuration.provider is ModelProvider.MINIMAX:
            return MiniMaxAdapter(**arguments)
        return OpenAICompatibleAdapter(provider=configuration.provider.value, **arguments)

    async def status(self, workspace_id: str) -> ModelStatus:
        configuration = await self.repository.get(workspace_id)
        if configuration is None:
            return ModelStatus(configured=False, provider="echo")
        try:
            credential_available = (
                self.credential_store.resolve(configuration.credential_ref) is not None
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
            "version": row["version"],
            "updated_at": row["updated_at"],
        }
    )
