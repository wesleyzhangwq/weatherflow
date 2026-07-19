from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID

from weatherflow.extensions import CredentialRef


class ConnectorKind(StrEnum):
    GITHUB = "github"
    GMAIL = "gmail"
    GOOGLE_CALENDAR = "google_calendar"
    SLACK = "slack"
    NOTION = "notion"
    GOOGLE_DRIVE = "google_drive"
    GOOGLE_SHEETS = "google_sheets"
    OUTLOOK = "outlook"
    ONE_DRIVE = "one_drive"
    MICROSOFT_TEAMS = "microsoft_teams"
    LINEAR = "linear"
    JIRA = "jira"
    CONFLUENCE = "confluence"
    DROPBOX = "dropbox"
    GITLAB = "gitlab"
    DISCORD = "discord"
    TRELLO = "trello"
    ASANA = "asana"
    AIRTABLE = "airtable"
    CLICKUP = "clickup"


class ConnectionPhase(StrEnum):
    WAITING_USER = "waiting_user"
    ACTIVE = "active"
    EXPIRED = "expired"
    ERROR = "error"
    REVOKED = "revoked"


class OAuthSetup(StrEnum):
    MANAGED = "managed"
    BRING_YOUR_OWN = "bring_your_own"
    UNKNOWN = "unknown"


DAILY_AUTO_FETCH_INTERVAL_MINUTES = 1_440
CONNECTOR_FETCH_CONTRACT_VERSION = "connector-fetch-v2-daily-source-specific"


class ConnectorRefreshCadence(StrEnum):
    DAILY = "daily"


class ConnectorFetchStrategy(StrEnum):
    GITHUB_UNREAD_NOTIFICATIONS_AND_RECENT_ACTIVITY = (
        "github_unread_notifications_and_recent_activity"
    )
    GMAIL_UNREAD_METADATA_30D = "gmail_unread_metadata_30d"
    GOOGLE_CALENDAR_ALL_CALENDARS_PAST_7D_FUTURE_14D = (
        "google_calendar_all_calendars_past_7d_future_14d"
    )


class ConnectorNormalizationHealth(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    PARTIAL = "partial"
    FAILED = "failed"


class ConnectorDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connector: ConnectorKind
    label: str
    category: str
    toolkit: str
    read_actions: tuple[str, ...]
    reviewed_auth_actions: tuple[str, ...]
    granted_scopes: frozenset[str]
    auto_fetch_supported: bool
    conversation_tools_supported: bool
    fetch_strategy: ConnectorFetchStrategy | None = None
    coverage_past_days: int = Field(default=0, ge=0, le=365)
    coverage_future_days: int = Field(default=0, ge=0, le=365)


CONNECTOR_DEFINITIONS: dict[ConnectorKind, ConnectorDefinition] = {
    ConnectorKind.GITHUB: ConnectorDefinition(
        connector=ConnectorKind.GITHUB,
        label="GitHub",
        category="development",
        toolkit="github",
        read_actions=(
            "GITHUB_GET_THE_AUTHENTICATED_USER",
            "GITHUB_LIST_NOTIFICATIONS",
            "GITHUB_SEARCH_COMMITS",
        ),
        reviewed_auth_actions=(
            "GITHUB_GET_THE_AUTHENTICATED_USER",
            "GITHUB_LIST_NOTIFICATIONS",
            "GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER",
            "GITHUB_SEARCH_COMMITS",
            "GITHUB_LIST_COMMITS",
            "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS",
            "GITHUB_GET_A_PULL_REQUEST",
            "GITHUB_LIST_BRANCHES",
            "GITHUB_CREATE_AN_ISSUE",
            "GITHUB_CREATE_A_PULL_REQUEST",
        ),
        granted_scopes=frozenset({"github:read", "github:write"}),
        auto_fetch_supported=True,
        conversation_tools_supported=True,
        fetch_strategy=(ConnectorFetchStrategy.GITHUB_UNREAD_NOTIFICATIONS_AND_RECENT_ACTIVITY),
        coverage_past_days=7,
    ),
    ConnectorKind.GMAIL: ConnectorDefinition(
        connector=ConnectorKind.GMAIL,
        label="Gmail",
        category="communication",
        toolkit="gmail",
        read_actions=("GMAIL_FETCH_EMAILS",),
        reviewed_auth_actions=(
            "GMAIL_FETCH_EMAILS",
            "GMAIL_CREATE_EMAIL_DRAFT",
            "GMAIL_SEND_EMAIL",
        ),
        granted_scopes=frozenset({"gmail:read", "gmail:write"}),
        auto_fetch_supported=True,
        conversation_tools_supported=True,
        fetch_strategy=ConnectorFetchStrategy.GMAIL_UNREAD_METADATA_30D,
        coverage_past_days=30,
    ),
    ConnectorKind.GOOGLE_CALENDAR: ConnectorDefinition(
        connector=ConnectorKind.GOOGLE_CALENDAR,
        label="Google Calendar",
        category="productivity",
        toolkit="googlecalendar",
        read_actions=("GOOGLECALENDAR_EVENTS_LIST_ALL_CALENDARS",),
        reviewed_auth_actions=(
            "GOOGLECALENDAR_EVENTS_LIST",
            "GOOGLECALENDAR_EVENTS_LIST_ALL_CALENDARS",
            "GOOGLECALENDAR_FIND_FREE_SLOTS",
            "GOOGLECALENDAR_CREATE_EVENT",
            "GOOGLECALENDAR_PATCH_EVENT",
            "GOOGLECALENDAR_DELETE_EVENT",
        ),
        granted_scopes=frozenset({"calendar:read", "calendar:write"}),
        auto_fetch_supported=True,
        conversation_tools_supported=True,
        fetch_strategy=(ConnectorFetchStrategy.GOOGLE_CALENDAR_ALL_CALENDARS_PAST_7D_FUTURE_14D),
        coverage_past_days=7,
        coverage_future_days=14,
    ),
    ConnectorKind.SLACK: ConnectorDefinition(
        connector=ConnectorKind.SLACK,
        label="Slack",
        category="communication",
        toolkit="slack",
        read_actions=(),
        reviewed_auth_actions=("SLACK_SEARCH_MESSAGES",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.NOTION: ConnectorDefinition(
        connector=ConnectorKind.NOTION,
        label="Notion",
        category="productivity",
        toolkit="notion",
        read_actions=(),
        reviewed_auth_actions=("NOTION_SEARCH_NOTION_PAGE",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.GOOGLE_DRIVE: ConnectorDefinition(
        connector=ConnectorKind.GOOGLE_DRIVE,
        label="Google Drive",
        category="storage",
        toolkit="googledrive",
        read_actions=(),
        reviewed_auth_actions=("GOOGLEDRIVE_FIND_FILE",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.GOOGLE_SHEETS: ConnectorDefinition(
        connector=ConnectorKind.GOOGLE_SHEETS,
        label="Google Sheets",
        category="data",
        toolkit="googlesheets",
        read_actions=(),
        reviewed_auth_actions=("GOOGLESHEETS_VALUES_GET",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.OUTLOOK: ConnectorDefinition(
        connector=ConnectorKind.OUTLOOK,
        label="Outlook",
        category="communication",
        toolkit="outlook",
        read_actions=(),
        reviewed_auth_actions=("OUTLOOK_QUERY_EMAILS",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.ONE_DRIVE: ConnectorDefinition(
        connector=ConnectorKind.ONE_DRIVE,
        label="OneDrive",
        category="storage",
        toolkit="one_drive",
        read_actions=(),
        reviewed_auth_actions=("ONE_DRIVE_ONEDRIVE_FIND_FILE",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.MICROSOFT_TEAMS: ConnectorDefinition(
        connector=ConnectorKind.MICROSOFT_TEAMS,
        label="Microsoft Teams",
        category="communication",
        toolkit="microsoft_teams",
        read_actions=(),
        reviewed_auth_actions=("MICROSOFT_TEAMS_SEARCH_MESSAGES",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.LINEAR: ConnectorDefinition(
        connector=ConnectorKind.LINEAR,
        label="Linear",
        category="productivity",
        toolkit="linear",
        read_actions=(),
        reviewed_auth_actions=("LINEAR_SEARCH_ISSUES",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.JIRA: ConnectorDefinition(
        connector=ConnectorKind.JIRA,
        label="Jira",
        category="productivity",
        toolkit="jira",
        read_actions=(),
        reviewed_auth_actions=("JIRA_GET_ISSUE",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.CONFLUENCE: ConnectorDefinition(
        connector=ConnectorKind.CONFLUENCE,
        label="Confluence",
        category="productivity",
        toolkit="confluence",
        read_actions=(),
        reviewed_auth_actions=("CONFLUENCE_CQL_SEARCH",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.DROPBOX: ConnectorDefinition(
        connector=ConnectorKind.DROPBOX,
        label="Dropbox",
        category="storage",
        toolkit="dropbox",
        read_actions=(),
        reviewed_auth_actions=("DROPBOX_FILES_SEARCH",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.GITLAB: ConnectorDefinition(
        connector=ConnectorKind.GITLAB,
        label="GitLab",
        category="development",
        toolkit="gitlab",
        read_actions=(),
        reviewed_auth_actions=("GITLAB_GET_PROJECT",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.DISCORD: ConnectorDefinition(
        connector=ConnectorKind.DISCORD,
        label="Discord",
        category="communication",
        toolkit="discord",
        read_actions=(),
        reviewed_auth_actions=("DISCORD_LIST_MY_GUILDS",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.TRELLO: ConnectorDefinition(
        connector=ConnectorKind.TRELLO,
        label="Trello",
        category="productivity",
        toolkit="trello",
        read_actions=(),
        reviewed_auth_actions=(),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.ASANA: ConnectorDefinition(
        connector=ConnectorKind.ASANA,
        label="Asana",
        category="productivity",
        toolkit="asana",
        read_actions=(),
        reviewed_auth_actions=("ASANA_SEARCH_TASKS_IN_WORKSPACE",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.AIRTABLE: ConnectorDefinition(
        connector=ConnectorKind.AIRTABLE,
        label="Airtable",
        category="data",
        toolkit="airtable",
        read_actions=(),
        reviewed_auth_actions=("AIRTABLE_LIST_RECORDS",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
    ConnectorKind.CLICKUP: ConnectorDefinition(
        connector=ConnectorKind.CLICKUP,
        label="ClickUp",
        category="productivity",
        toolkit="clickup",
        read_actions=(),
        reviewed_auth_actions=("CLICKUP_GET_TASKS",),
        granted_scopes=frozenset(),
        auto_fetch_supported=False,
        conversation_tools_supported=False,
    ),
}


class ConnectorAccount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    workspace_id: str
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
        workspace_id: str,
        connector: ConnectorKind,
        external_account_id: str,
        credential_ref: CredentialRef,
        now: datetime | None = None,
    ) -> "ConnectorAccount":
        observed = now or datetime.now(UTC)
        return cls(
            id=str(ULID()),
            workspace_id=workspace_id,
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
    interval_minutes: int = Field(
        default=DAILY_AUTO_FETCH_INTERVAL_MINUTES,
        ge=DAILY_AUTO_FETCH_INTERVAL_MINUTES,
        le=DAILY_AUTO_FETCH_INTERVAL_MINUTES,
    )
    fetch_contract_version: Literal["connector-fetch-v2-daily-source-specific"] = (
        CONNECTOR_FETCH_CONTRACT_VERSION
    )
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
            auto_fetch_enabled=CONNECTOR_DEFINITIONS[connector].auto_fetch_supported,
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
                "last_sync_at": self.last_sync_at if error_code else now,
                "next_sync_at": now + timedelta(minutes=self.interval_minutes),
                "last_error_code": error_code,
                "version": self.version + 1,
                "updated_at": now,
            }
        )

    def after_broker_revalidated(self, *, now: datetime) -> "ConnectorBinding":
        credential_errors = {"broker_auth", "broker_permission"}
        credential_repaired = self.last_error_code in credential_errors
        return self.model_copy(
            update={
                "next_sync_at": (
                    now
                    if credential_repaired and self.enabled and self.auto_fetch_enabled
                    else self.next_sync_at
                ),
                "last_error_code": (None if credential_repaired else self.last_error_code),
                "version": self.version + 1,
                "updated_at": now,
            }
        )

    def after_broker_failure(
        self,
        *,
        now: datetime,
        error_code: str,
    ) -> "ConnectorBinding":
        return self.model_copy(
            update={
                "next_sync_at": now + timedelta(minutes=self.interval_minutes),
                "last_error_code": error_code,
                "version": self.version + 1,
                "updated_at": now,
            }
        )

    def require_reconnect(
        self,
        *,
        now: datetime,
        error_code: str = "project_changed",
    ) -> "ConnectorBinding":
        return self.model_copy(
            update={
                "enabled": False,
                "last_error_code": error_code,
                "next_sync_at": now,
                "version": self.version + 1,
                "updated_at": now,
            }
        )


class SourceItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1, max_length=500)
    occurred_at: datetime
    ends_at: datetime | None = None
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(max_length=2_000)
    url: str | None = Field(default=None, max_length=2_000)
    untrusted: Literal[True] = True


class ConnectorFeedHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    REQUIRES_RECONNECT = "requires_reconnect"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    STALE = "stale"


class ConnectorFeedItem(SourceItem):
    connector: ConnectorKind


class ConnectorFeedSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connector: ConnectorKind
    label: str
    health: ConnectorFeedHealth
    connected: bool
    enabled: bool
    stale: bool
    item_count: int = Field(ge=0, le=10)
    last_sync_at: datetime | None = None
    next_sync_at: datetime | None = None
    snapshot_fetched_at: datetime | None = None
    refresh_cadence: ConnectorRefreshCadence = ConnectorRefreshCadence.DAILY
    fetch_strategy: ConnectorFetchStrategy
    coverage_past_days: int = Field(ge=0, le=365)
    coverage_future_days: int = Field(ge=0, le=365)
    raw_item_count: int | None = Field(default=None, ge=0)
    normalized_item_count: int | None = Field(default=None, ge=0, le=100)
    normalization_health: ConnectorNormalizationHealth = ConnectorNormalizationHealth.UNKNOWN
    last_error_code: str | None = Field(default=None, max_length=100)


class ConnectorFeed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    generated_at: datetime
    sources: tuple[ConnectorFeedSource, ...] = Field(max_length=3)
    items: tuple[ConnectorFeedItem, ...] = Field(max_length=30)


class ConnectorSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    connector: ConnectorKind
    fetched_at: datetime
    expires_at: datetime
    raw_item_count: int | None = Field(default=None, ge=0)
    normalized_item_count: int | None = Field(default=None, ge=0, le=100)
    items: tuple[SourceItem, ...] = Field(max_length=100)


class ConnectorStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connector: ConnectorKind
    label: str
    category: str = "other"
    toolkit: str = ""
    auto_fetch_supported: bool = False
    conversation_tools_supported: bool = False
    oauth_setup: OAuthSetup = OAuthSetup.UNKNOWN
    phase: ConnectionPhase | None
    configured: bool
    connected: bool
    display_name: str | None = None
    auto_fetch_enabled: bool = False
    interval_minutes: int = DAILY_AUTO_FETCH_INTERVAL_MINUTES
    last_sync_at: datetime | None = None
    next_sync_at: datetime | None = None
    last_error_code: str | None = None
    available_tool_ids: tuple[str, ...] = ()
    attempt_id: str | None = None
    attempt_expires_at: datetime | None = None


class ConnectHandoff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_id: str
    connect_url: str
    expires_at: datetime


class RunConnectorRoute(BaseModel):
    """Opaque connector identity frozen for the lifetime of one Run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    workspace_id: str
    connector: ConnectorKind
    account_id: str
    external_account_id: str = Field(min_length=1, max_length=256)
    bound_at: datetime
