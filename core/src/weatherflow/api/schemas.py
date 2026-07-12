from typing import Literal

from pydantic import BaseModel, ConfigDict

from weatherflow.capabilities import ToolEffect
from weatherflow.models import ModelConfiguration, ModelProvider, ModelStatus, ProviderPreset
from weatherflow.rhythm import CurrentRhythm
from weatherflow.runs import Run
from weatherflow.trust import Approval
from weatherflow.workspaces import Workspace


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    service: Literal["weatherflow-core"] = "weatherflow-core"
    version: str


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_intent: str
    client_request_id: str | None = None
    workspace_id: str
    context_run_id: str | None = None
    execute: bool = False


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    path: str


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: Literal["approve", "deny"]
    expected_version: int
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
    model_config = ConfigDict(frozen=True)

    provider: ModelProvider
    model: str
    base_url: str
    api_key: str


class ModelConfigurationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    configuration: ModelConfiguration
    status: ModelStatus


class ModelProviderList(BaseModel):
    model_config = ConfigDict(frozen=True)

    providers: tuple[ProviderPreset, ...]
