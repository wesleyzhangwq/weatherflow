from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class LocalMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_counts: dict[str, int]
    action_counts: dict[str, int]
    event_count: int = Field(ge=0)
    pending_approvals: int = Field(ge=0)


class DiagnosticExport(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    path: Path
    sha256: str
    size_bytes: int = Field(ge=0)


class ResetCategory(StrEnum):
    BEHAVIOR = "behavior"
    MEMORY = "memory"
    PROFILE = "profile"
    ARTIFACTS = "artifacts"
    WORKSPACE = "workspace"


class ResetPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: ResetCategory
    count: int = Field(ge=0)


class ResetResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: ResetCategory
    deleted_count: int = Field(ge=0)


class SecurityFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    table: str
    row_id: str
    field: str
    kind: str


class SecurityScan(BaseModel):
    model_config = ConfigDict(frozen=True)

    findings: tuple[SecurityFinding, ...]


class OnboardingState(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: str
    completed: bool = False
    metadata_sensor_enabled: bool = False
    version: int = Field(default=0, ge=0)
