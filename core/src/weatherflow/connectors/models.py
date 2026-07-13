from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID

from weatherflow.extensions import CredentialRef


class ConnectorKind(StrEnum):
    GITHUB = "github"
    GMAIL = "gmail"
    GOOGLE_CALENDAR = "google_calendar"


class ConnectionPhase(StrEnum):
    WAITING_USER = "waiting_user"
    ACTIVE = "active"
    EXPIRED = "expired"
    ERROR = "error"
    REVOKED = "revoked"


class ConnectorDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connector: ConnectorKind
    label: str
    toolkit: str
    read_actions: tuple[str, ...]
    granted_scopes: frozenset[str]


CONNECTOR_DEFINITIONS: dict[ConnectorKind, ConnectorDefinition] = {
    ConnectorKind.GITHUB: ConnectorDefinition(
        connector=ConnectorKind.GITHUB,
        label="GitHub",
        toolkit="github",
        read_actions=(
            "GITHUB_GET_THE_AUTHENTICATED_USER",
            "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS",
        ),
        granted_scopes=frozenset({"github:read"}),
    ),
    ConnectorKind.GMAIL: ConnectorDefinition(
        connector=ConnectorKind.GMAIL,
        label="Gmail",
        toolkit="gmail",
        read_actions=("GMAIL_FETCH_EMAILS",),
        granted_scopes=frozenset({"gmail:read"}),
    ),
    ConnectorKind.GOOGLE_CALENDAR: ConnectorDefinition(
        connector=ConnectorKind.GOOGLE_CALENDAR,
        label="Google Calendar",
        toolkit="googlecalendar",
        read_actions=("GOOGLECALENDAR_EVENTS_LIST",),
        granted_scopes=frozenset({"calendar:read"}),
    ),
}


class ConnectorAccount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    connector: ConnectorKind
    external_account_id: str = Field(min_length=1, max_length=256)
    credential_ref: CredentialRef
    phase: ConnectionPhase
    display_name: str | None = Field(default=None, max_length=300)
    version: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def new(
        cls,
        *,
        connector: ConnectorKind,
        external_account_id: str,
        credential_ref: CredentialRef,
        now: datetime | None = None,
    ) -> "ConnectorAccount":
        observed = now or datetime.now(UTC)
        return cls(
            id=str(ULID()),
            connector=connector,
            external_account_id=external_account_id,
            credential_ref=credential_ref,
            phase=ConnectionPhase.WAITING_USER,
            created_at=observed,
            updated_at=observed,
        )

    def with_phase(
        self,
        phase: ConnectionPhase,
        *,
        now: datetime | None = None,
        display_name: str | None = None,
    ) -> "ConnectorAccount":
        return self.model_copy(
            update={
                "phase": phase,
                "display_name": display_name if display_name is not None else self.display_name,
                "version": self.version + 1,
                "updated_at": now or datetime.now(UTC),
            }
        )

    def activate(
        self, *, now: datetime | None = None, display_name: str | None = None
    ) -> "ConnectorAccount":
        return self.with_phase(ConnectionPhase.ACTIVE, now=now, display_name=display_name)


class ConnectionAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    workspace_id: str
    connector: ConnectorKind
    account_id: str
    external_account_id: str
    phase: ConnectionPhase = ConnectionPhase.WAITING_USER
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    @classmethod
    def new(
        cls,
        *,
        workspace_id: str,
        connector: ConnectorKind,
        account_id: str,
        external_account_id: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> "ConnectionAttempt":
        observed = now or datetime.now(UTC)
        return cls(
            id=str(ULID()),
            workspace_id=workspace_id,
            connector=connector,
            account_id=account_id,
            external_account_id=external_account_id,
            expires_at=expires_at,
            created_at=observed,
            updated_at=observed,
        )

    def with_phase(
        self, phase: ConnectionPhase, *, now: datetime | None = None
    ) -> "ConnectionAttempt":
        return self.model_copy(update={"phase": phase, "updated_at": now or datetime.now(UTC)})


class ConnectorBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    connector: ConnectorKind
    account_id: str
    enabled: bool = True
    auto_fetch_enabled: bool = True
    interval_minutes: int = Field(default=60, ge=15, le=1440)
    granted_scopes: frozenset[str]
    last_sync_at: datetime | None = None
    next_sync_at: datetime
    last_error_code: str | None = Field(default=None, max_length=100)
    version: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def new(
        cls,
        *,
        workspace_id: str,
        connector: ConnectorKind,
        account_id: str,
        now: datetime | None = None,
    ) -> "ConnectorBinding":
        observed = now or datetime.now(UTC)
        return cls(
            workspace_id=workspace_id,
            connector=connector,
            account_id=account_id,
            granted_scopes=CONNECTOR_DEFINITIONS[connector].granted_scopes,
            next_sync_at=observed,
            created_at=observed,
            updated_at=observed,
        )

    def after_sync(
        self,
        *,
        now: datetime,
        error_code: str | None = None,
    ) -> "ConnectorBinding":
        return self.model_copy(
            update={
                "last_sync_at": None if error_code else now,
                "next_sync_at": now + timedelta(minutes=self.interval_minutes),
                "last_error_code": error_code,
                "version": self.version + 1,
                "updated_at": now,
            }
        )


class SourceItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1, max_length=500)
    occurred_at: datetime
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(max_length=2_000)
    url: str | None = Field(default=None, max_length=2_000)


class ConnectorSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    connector: ConnectorKind
    fetched_at: datetime
    expires_at: datetime
    items: tuple[SourceItem, ...] = Field(max_length=100)


class ConnectorStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connector: ConnectorKind
    label: str
    phase: ConnectionPhase | None
    configured: bool
    connected: bool
    display_name: str | None = None
    auto_fetch_enabled: bool = False
    interval_minutes: int = 60
    last_sync_at: datetime | None = None
    next_sync_at: datetime | None = None
    last_error_code: str | None = None
    attempt_id: str | None = None
    attempt_expires_at: datetime | None = None


class ConnectHandoff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_id: str
    connect_url: str
    expires_at: datetime
