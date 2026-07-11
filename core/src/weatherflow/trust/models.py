from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID

from weatherflow.capabilities import ToolEffect


class InvalidActionTransition(ValueError):
    pass


class InvalidApprovalTransition(ValueError):
    pass


class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    DENIED = "denied"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    CANCELLED = "cancelled"

    def can_transition_to(self, target: "ActionStatus") -> bool:
        return target in ACTION_TRANSITIONS[self]

    def require_transition(self, target: "ActionStatus") -> None:
        if not self.can_transition_to(target):
            raise InvalidActionTransition(f"{self.value} -> {target.value}")


ACTION_TRANSITIONS: dict[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.PROPOSED: frozenset(
        {ActionStatus.APPROVED, ActionStatus.DENIED, ActionStatus.CANCELLED}
    ),
    ActionStatus.APPROVED: frozenset({ActionStatus.EXECUTING}),
    ActionStatus.DENIED: frozenset(),
    ActionStatus.EXECUTING: frozenset(
        {ActionStatus.SUCCEEDED, ActionStatus.FAILED, ActionStatus.NEEDS_REVIEW}
    ),
    ActionStatus.SUCCEEDED: frozenset(),
    ActionStatus.FAILED: frozenset(),
    ActionStatus.NEEDS_REVIEW: frozenset(),
    ActionStatus.CANCELLED: frozenset(),
}


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

    def can_transition_to(self, target: "ApprovalStatus") -> bool:
        return target in APPROVAL_TRANSITIONS[self]

    def require_transition(self, target: "ApprovalStatus") -> None:
        if not self.can_transition_to(target):
            raise InvalidApprovalTransition(f"{self.value} -> {target.value}")


APPROVAL_TRANSITIONS: dict[ApprovalStatus, frozenset[ApprovalStatus]] = {
    ApprovalStatus.PENDING: frozenset(
        {
            ApprovalStatus.APPROVED,
            ApprovalStatus.DENIED,
            ApprovalStatus.EXPIRED,
            ApprovalStatus.CANCELLED,
        }
    ),
    ApprovalStatus.APPROVED: frozenset(),
    ApprovalStatus.DENIED: frozenset(),
    ApprovalStatus.EXPIRED: frozenset(),
    ApprovalStatus.CANCELLED: frozenset(),
}


class Action(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    run_id: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)
    arguments: dict[str, Any]
    effect: ToolEffect
    status: ActionStatus
    idempotency_key: str = Field(min_length=1)
    preview: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=0)
    result: dict[str, Any] | None = None
    error_class: str | None = None
    error_message: str | None = None

    @classmethod
    def new(
        cls,
        *,
        run_id: str,
        tool_id: str,
        arguments: dict[str, Any],
        effect: ToolEffect,
        idempotency_key: str,
        preview: dict[str, Any],
    ) -> "Action":
        now = datetime.now(UTC)
        return cls(
            id=str(ULID()),
            run_id=run_id,
            tool_id=tool_id,
            arguments=arguments,
            effect=effect,
            status=ActionStatus.PROPOSED,
            idempotency_key=idempotency_key,
            preview=preview,
            created_at=now,
            updated_at=now,
            version=0,
        )


class Approval(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    action_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    status: ApprovalStatus
    requested_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    rationale: str | None = None
    version: int = Field(ge=0)

    @classmethod
    def for_action(cls, action: Action) -> "Approval":
        return cls(
            id=str(ULID()),
            action_id=action.id,
            run_id=action.run_id,
            status=ApprovalStatus.PENDING,
            requested_at=datetime.now(UTC),
            version=0,
        )
