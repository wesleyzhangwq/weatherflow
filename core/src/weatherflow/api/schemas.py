from datetime import datetime
from typing import Literal

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
from weatherflow.rhythm import CurrentRhythm
from weatherflow.runs import Run, ToolMode
from weatherflow.runtime import RunControlKind
from weatherflow.trust import Approval
from weatherflow.workspaces import Workspace


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    service: Literal["weatherflow-core"] = "weatherflow-core"
    version: str


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
    metadata_sensor_enabled: bool = False


class ApprovalView(Approval):
    tool_id: str
    effect: ToolEffect
    preview: dict


class ResetConfirmRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    confirm: bool = False


class OnboardingCompleteRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    confirm_local_ownership: bool
    enable_metadata_sensor: bool = False


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
    interval_minutes: int = Field(ge=15, le=1440)


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
