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
from weatherflow.models.minimax import MiniMaxAdapter
from weatherflow.storage import Database


class ModelProvider(StrEnum):
    MINIMAX = "minimax"


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
        reference = CredentialRef(provider="minimax", name="api_key")
        candidate = ModelConfiguration(
            workspace_id=workspace_id,
            provider=ModelProvider.MINIMAX,
            model=model,
            base_url=base_url,
            credential_ref=reference,
            updated_at=datetime.now(UTC),
        )
        verifier = MiniMaxAdapter(
            broker=CredentialBroker(MappingCredentialStore({reference.key: api_key})),
            credential_ref=reference,
            model=candidate.model,
            base_url=candidate.base_url,
            client=self.client,
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

    def adapter(self, configuration: ModelConfiguration) -> MiniMaxAdapter:
        return MiniMaxAdapter(
            broker=CredentialBroker(self.credential_store),
            credential_ref=configuration.credential_ref,
            model=configuration.model,
            base_url=configuration.base_url,
            client=self.client,
        )

    async def status(self, workspace_id: str) -> ModelStatus:
        configuration = await self.repository.get(workspace_id)
        if configuration is None:
            return ModelStatus(configured=False, provider="echo")
        return ModelStatus(
            configured=True,
            provider=configuration.provider.value,
            model=configuration.model,
            base_url=configuration.base_url,
            credential_available=(
                self.credential_store.resolve(configuration.credential_ref) is not None
            ),
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
