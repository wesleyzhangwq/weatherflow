from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID


class InvalidTransitionError(ValueError):
    pass


class RunStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_USER = "waiting_user"
    PAUSED = "paused"
    NEEDS_REVIEW = "needs_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def can_transition_to(self, target: "RunStatus") -> bool:
        return target in TRANSITIONS[self]

    def require_transition(self, target: "RunStatus") -> None:
        if not self.can_transition_to(target):
            raise InvalidTransitionError(f"{self.value} -> {target.value}")


class ToolMode(StrEnum):
    """Run-scoped visibility filter for the reviewed tool catalog."""

    ASK = "ask"
    BYPASS = "bypass"


TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.PLANNING, RunStatus.NEEDS_REVIEW, RunStatus.CANCELLED}),
    RunStatus.PLANNING: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.WAITING_USER,
            RunStatus.PAUSED,
            RunStatus.NEEDS_REVIEW,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING_APPROVAL,
            RunStatus.WAITING_USER,
            RunStatus.PAUSED,
            RunStatus.NEEDS_REVIEW,
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.WAITING_APPROVAL: frozenset(
        {RunStatus.RUNNING, RunStatus.PAUSED, RunStatus.CANCELLED}
    ),
    RunStatus.WAITING_USER: frozenset({RunStatus.PLANNING, RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.PAUSED: frozenset(
        {RunStatus.PLANNING, RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.NEEDS_REVIEW: frozenset({RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


class RunBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_steps: int = Field(default=20, ge=1)
    max_cost_usd: float | None = Field(default=None, ge=0)
    timeout_seconds: int = Field(default=1800, ge=1)


class Run(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    client_request_id: str
    user_intent: str
    workspace_id: str
    session_id: str | None = None
    tool_mode: ToolMode = ToolMode.ASK
    status: RunStatus
    version: int
    created_at: datetime
    updated_at: datetime
    rhythm_snapshot_id: str | None = None
    capability_snapshot_id: str | None = None
    policy_profile: str = "supervised"
    budget: RunBudget = RunBudget()
    checkpoint_ref: str | None = None
    result_summary: str | None = None
    error_class: str | None = None
    error_message: str | None = None

    @classmethod
    def new(
        cls,
        *,
        client_request_id: str,
        user_intent: str,
        workspace_id: str,
        session_id: str | None = None,
        tool_mode: ToolMode = ToolMode.ASK,
        budget: RunBudget | None = None,
    ) -> "Run":
        now = datetime.now(UTC)
        values = dict(
            id=str(ULID()),
            client_request_id=client_request_id,
            user_intent=user_intent,
            workspace_id=workspace_id,
            session_id=session_id,
            tool_mode=tool_mode,
            status=RunStatus.QUEUED,
            version=0,
            created_at=now,
            updated_at=now,
        )
        if budget is not None:
            values["budget"] = budget
        return cls.model_validate(values)
