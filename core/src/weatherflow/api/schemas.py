from typing import Literal

from pydantic import BaseModel, ConfigDict

from weatherflow.rhythm import CurrentRhythm
from weatherflow.runs import Run


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    service: Literal["weatherflow-core"] = "weatherflow-core"
    version: str


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_intent: str
    client_request_id: str | None = None
    workspace_id: str | None = None
    execute: bool = False


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
