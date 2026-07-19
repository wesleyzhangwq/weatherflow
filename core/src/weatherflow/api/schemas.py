from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from weatherflow.automations import ScheduleSpec
from weatherflow.capabilities import ToolEffect
from weatherflow.models import (
    ModelConfiguration,
    ModelProvider,
    ModelStatus,
    ProviderPreset,
    normalize_model_base_url,
)
from weatherflow.rhythm import (
    CheckInSignal,
    CorrectionSignal,
    CurrentRhythm,
    TaskBehaviorSignal,
)
from weatherflow.runs import Run, ToolMode
from weatherflow.runtime import RunControlKind
from weatherflow.trust import Approval
from weatherflow.workspaces import Workspace


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    service: Literal["weatherflow-core"] = "weatherflow-core"
    version: str


class ForbiddenActivityMetadataRequest(BaseModel):
    """API-only tombstone for the removed WeatherFlow watcher ingest path."""

    model_config = ConfigDict(frozen=True, extra="allow")

    kind: Literal["activity_metadata"]


RhythmSignalRequest = Annotated[
    CheckInSignal | CorrectionSignal | TaskBehaviorSignal | ForbiddenActivityMetadataRequest,
    Field(discriminator="kind"),
]


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    user_intent: str = Field(min_length=1, max_length=20_000)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=200)
    workspace_id: str = Field(min_length=1, max_length=200)
    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    context_run_id: str | None = Field(default=None, min_length=1, max_length=200)
    tool_mode: ToolMode = ToolMode.ASK
    execute: bool = False


class RunControlCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    kind: RunControlKind
    content: str = Field(min_length=1, max_length=20_000)


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    workspace_id: str
    title: str = Field(default="新对话", min_length=1, max_length=160)


class SessionUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=160)
    pinned: bool | None = None

    @model_validator(mode="after")
    def has_update(self) -> "SessionUpdateRequest":
        if self.title is None and self.pinned is None:
            raise ValueError("at least one session field must be updated")
        return self


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    path: str


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["approve", "deny"]
    expected_version: int
    workspace_id: str | None = None
    rationale: str | None = None
    resume: bool = True


class DesktopSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    rhythm: CurrentRhythm
    latest_run: Run | None = None
    workspace: Workspace


class ApprovalView(Approval):
    tool_id: str
    effect: ToolEffect
    preview: dict


class ResetConfirmRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    confirm: bool = False


class OnboardingCompleteRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    confirm_local_ownership: bool


class OnboardingView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    workspace_id: str
    completed: bool
    version: int = Field(ge=0)


class SystemStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    local_only: Literal[True] = True
    telemetry_upload: Literal[False] = False
    onboarding_completed: bool
    workspace_id: str
    installed_packs: tuple[str, ...]
    providers: dict[str, str]
    behavior_sensor: dict[str, bool | str]
    retention: dict[str, str]
    model: ModelStatus


class ModelConfigureRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    provider: ModelProvider
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=500)

    @field_validator("base_url")
    @classmethod
    def valid_base_url(cls, value: str) -> str:
        return normalize_model_base_url(value)


class ModelConfigurationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    configuration: ModelConfiguration
    status: ModelStatus


class ModelProviderList(BaseModel):
    model_config = ConfigDict(frozen=True)

    providers: tuple[ProviderPreset, ...]


class ConnectorConfigureResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    configured: bool = True


class ConnectorSettingsRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    auto_fetch_enabled: bool
    interval_minutes: Literal[1440]


class ConnectorDisconnectRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    confirm: bool = False


class AutomationCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    name: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=20_000)
    schedule: ScheduleSpec


class AutomationUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_version: int = Field(ge=0)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    prompt: str | None = Field(default=None, min_length=1, max_length=20_000)
    schedule: ScheduleSpec | None = None


class VersionedRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_version: int = Field(ge=0)
    confirm: bool = True


class ActivityEvidenceRefView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    activitywatch_server_id: str | None = None
    bucket_id: str
    event_id: str
    event_timestamp: datetime | None = None
    event_duration: float | None = Field(default=None, ge=0)
    event_digest: str | None = None
    fields_used: tuple[str, ...] = ()


class ActivityConnectorEvidenceRefView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connector: Literal["github", "gmail", "google_calendar"]
    source_id_digest: str
    occurred_at: datetime
    ends_at: datetime | None
    item_digest: str
    snapshot_fetched_at: datetime


class ActivityConnectorCoverageView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connector: Literal["github", "gmail", "google_calendar"]
    health: Literal[
        "healthy",
        "degraded",
        "requires_reconnect",
        "disabled",
        "unavailable",
        "stale",
    ]
    connected: bool
    enabled: bool
    stale: bool
    snapshot_fetched_at: datetime | None
    window_item_count: int = Field(ge=0, le=30)
    snapshot_watermark: str = Field(min_length=64, max_length=64)


class ActivityWatchSourceStatusView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reachable: bool
    server_version: str | None
    data_start: datetime | None
    data_end: datetime | None
    checked_at: datetime
    last_reconciled_at: datetime | None
    error_code: str | None


class ActivityObservedFactView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    observed_at: datetime
    started_at: datetime
    duration_seconds: float = Field(ge=0)
    app_name: str | None
    window_title: str | None
    url: str | None
    afk_state: Literal["active", "afk", "unknown"]
    evidence_refs: tuple[ActivityEvidenceRefView, ...]


class WatchCurrentView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    observed: ActivityObservedFactView | None
    afk_state: Literal["active", "afk", "unknown"]
    observed_at: datetime
    source_health: Literal["available", "degraded"]


WatchOAuthConnector = Literal["github", "gmail", "google_calendar"]
WatchOAuthSourceHealth = Literal[
    "healthy",
    "degraded",
    "requires_reconnect",
    "disabled",
    "unavailable",
    "stale",
]
WatchOAuthRefreshCadence = Literal["daily"]
WatchOAuthFetchStrategy = Literal[
    "github_unread_notifications_and_recent_activity",
    "gmail_unread_metadata_30d",
    "google_calendar_all_calendars_past_7d_future_14d",
]
WatchOAuthNormalizationHealth = Literal["unknown", "healthy", "partial", "failed"]


class WatchOAuthFeedItemView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connector: WatchOAuthConnector
    source_id: str = Field(min_length=1, max_length=500)
    occurred_at: datetime
    ends_at: datetime | None = None
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(max_length=2_000)
    url: str | None = Field(default=None, max_length=2_000)
    untrusted: Literal[True] = True


class WatchOAuthFeedSourceView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connector: WatchOAuthConnector
    label: str
    health: WatchOAuthSourceHealth
    connected: bool
    enabled: bool
    stale: bool
    item_count: int = Field(ge=0, le=10)
    last_sync_at: datetime | None = None
    next_sync_at: datetime | None = None
    snapshot_fetched_at: datetime | None = None
    refresh_cadence: WatchOAuthRefreshCadence
    fetch_strategy: WatchOAuthFetchStrategy
    coverage_past_days: int = Field(ge=0, le=365)
    coverage_future_days: int = Field(ge=0, le=365)
    raw_item_count: int | None = Field(default=None, ge=0)
    normalized_item_count: int | None = Field(default=None, ge=0, le=100)
    normalization_health: WatchOAuthNormalizationHealth
    last_error_code: str | None = Field(default=None, max_length=100)


class WatchOAuthFeedView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    generated_at: datetime
    sources: tuple[WatchOAuthFeedSourceView, ...] = Field(max_length=3)
    items: tuple[WatchOAuthFeedItemView, ...] = Field(max_length=30)


class ActivityStatisticsView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    window_start: datetime
    window_end: datetime
    active_seconds: float = Field(ge=0)
    afk_seconds: float = Field(ge=0)
    browser_seconds: float = Field(default=0, ge=0)
    app_switch_count: int = Field(ge=0)
    category_switch_count: int = Field(ge=0)
    app_seconds: dict[str, float]
    category_seconds: dict[str, float]
    category_rule_version: str
    observed_seconds: float = Field(default=0, ge=0)
    unobserved_seconds: float = Field(default=0, ge=0)
    window_observed_seconds: float = Field(default=0, ge=0)
    afk_observed_seconds: float = Field(default=0, ge=0)
    web_observed_seconds: float = Field(default=0, ge=0)
    coverage_ratio: float = Field(default=0, ge=0, le=1)
    coverage_status: Literal["none", "partial", "complete"] = "none"
    source_bucket_ids: tuple[str, ...] = ()


class ActivityTimelineEntryView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: float = Field(ge=0)
    app_name: str | None
    category: str | None
    afk_state: Literal["active", "afk", "unknown"]
    window_title: str | None = None
    url: str | None = None
    evidence_refs: tuple[ActivityEvidenceRefView, ...] = ()


class ActivityWatchDashboardView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    statistics: ActivityStatisticsView
    timeline: tuple[ActivityTimelineEntryView, ...]


class ActivitySummaryView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    task_id: str
    kind: Literal["stage_6h", "daily_24h", "weekly", "biweekly", "monthly"]
    finality: Literal["provisional", "final"]
    timezone: Literal["Asia/Shanghai"]
    window_start: datetime
    window_end: datetime
    statistics: ActivityStatisticsView
    narrative: str
    evidence_refs: tuple[ActivityEvidenceRefView, ...]
    connector_evidence_refs: tuple[ActivityConnectorEvidenceRefView, ...] = ()
    connector_coverage: tuple[ActivityConnectorCoverageView, ...] = ()
    category_rule_version: str
    rules_stale: bool
    provider: str | None = None
    model_version: str | None = None
    requested_provider: str | None = None
    requested_model: str | None = None
    fallback_reason: str | None = Field(default=None, max_length=120)
    summary_settings_version: int = Field(default=0, ge=0)
    prompt_version: str
    completed_at: datetime
    attempt_count: int | None = Field(default=None, ge=0)
    source_watermark: str | None = None
    evidence_count: int | None = Field(default=None, ge=0)


class ActivitySummaryTaskView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: Literal["stage_6h", "daily_24h", "weekly", "biweekly", "monthly"]
    window_start: datetime
    window_end: datetime
    status: Literal["pending", "running", "completed", "failed", "needs_retry"]
    attempt_count: int = Field(ge=0)
    completed_at: datetime | None
    next_attempt_at: datetime | None
    error_code: str | None
    finality: Literal["provisional", "final"] | None = None
    regeneration_reason: str | None = None


class ActivityRegenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    reason: str = Field(default="user_requested", min_length=1, max_length=200)


class ActivitySummarySettingsView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_workspace_id: str
    provider: str | None
    model: str | None
    model_configuration_version: int | None = Field(default=None, ge=0)
    prompt_version: str
    version: int = Field(ge=0)
    updated_at: datetime


class ActivitySummarySettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    model_workspace_id: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=200)
    expected_version: int = Field(ge=0)


class ActivityTrendPointView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    window_start: datetime
    window_end: datetime
    active_seconds: float = Field(ge=0)
    afk_seconds: float = Field(ge=0)
    app_switch_count: int = Field(ge=0)
    dominant_category: str | None


class ActivityEvidenceView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bucket_id: str
    event_id: str
    timestamp: datetime
    duration_seconds: float = Field(ge=0)
    source: str
    app_name: str | None
    window_title: str | None
    url: str | None
    afk_state: Literal["active", "afk", "unknown"]


class SkillMutationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    expected_workspace_version: int = Field(ge=0)
    confirm: bool = False


class SkillInstallRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    expected_workspace_version: int = Field(ge=0)
    client_request_id: str = Field(min_length=1, max_length=200)


class MCPMutationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    confirm: bool = False


class MCPInstallRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    client_request_id: str = Field(min_length=1, max_length=200)


class MCPPresetView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    preset_id: str
    title: str
    description: str
    publisher: str
    source_url: str
    version: str
    capabilities: tuple[str, ...]
    risk_note: str
    available: bool
    unavailable_reason: str | None = None
    installed: bool
    enabled: bool
    health: Literal["not_installed", "disabled", "healthy", "unavailable"]
    tool_ids: tuple[str, ...] = ()
    installed_at: datetime | None = None
    checked_at: datetime | None = None
