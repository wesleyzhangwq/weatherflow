from datetime import UTC, datetime, timedelta
from enum import StrEnum

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


CONNECTOR_DEFINITIONS: dict[ConnectorKind, ConnectorDefinition] = {
    ConnectorKind.GITHUB: ConnectorDefinition(
        connector=ConnectorKind.GITHUB,
        label="GitHub",
        category="development",
        toolkit="github",
        read_actions=(
            "GITHUB_GET_THE_AUTHENTICATED_USER",
            "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS",
        ),
        reviewed_auth_actions=(
            "GITHUB_GET_THE_AUTHENTICATED_USER",
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
    ),
    ConnectorKind.GOOGLE_CALENDAR: ConnectorDefinition(
        connector=ConnectorKind.GOOGLE_CALENDAR,
        label="Google Calendar",
        category="productivity",
        toolkit="googlecalendar",
        read_actions=("GOOGLECALENDAR_EVENTS_LIST",),
        reviewed_auth_actions=(
            "GOOGLECALENDAR_EVENTS_LIST",
            "GOOGLECALENDAR_FIND_FREE_SLOTS",
            "GOOGLECALENDAR_CREATE_EVENT",
            "GOOGLECALENDAR_PATCH_EVENT",
            "GOOGLECALENDAR_DELETE_EVENT",
        ),
        granted_scopes=frozenset({"calendar:read", "calendar:write"}),
        auto_fetch_supported=True,
        conversation_tools_supported=True,
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
    interval_minutes: int = 60
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
