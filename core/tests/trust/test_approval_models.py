import pytest

from weatherflow.capabilities import ToolEffect
from weatherflow.trust import (
    Action,
    ActionStatus,
    Approval,
    ApprovalStatus,
    InvalidActionTransition,
    InvalidApprovalTransition,
)


def test_new_action_is_a_stable_proposal() -> None:
    action = Action.new(
        run_id="run-1",
        tool_id="github.create_release",
        arguments={"tag": "v3.0.0"},
        effect=ToolEffect.EXTERNAL_WRITE,
        idempotency_key="run-1:release-v3",
        preview={"summary": "Create GitHub release v3.0.0"},
    )

    assert len(action.id) == 26
    assert action.status is ActionStatus.PROPOSED
    assert action.version == 0
    assert action.idempotency_key == "run-1:release-v3"


def test_approval_for_action_is_pending() -> None:
    action = Action.new(
        run_id="run-1",
        tool_id="github.create_release",
        arguments={},
        effect=ToolEffect.EXTERNAL_WRITE,
        idempotency_key="release-v3",
        preview={},
    )

    approval = Approval.for_action(action)

    assert len(approval.id) == 26
    assert approval.action_id == action.id
    assert approval.run_id == action.run_id
    assert approval.status is ApprovalStatus.PENDING
    assert approval.version == 0


def test_action_transitions_are_deterministic() -> None:
    assert ActionStatus.PROPOSED.can_transition_to(ActionStatus.APPROVED)
    assert ActionStatus.PROPOSED.can_transition_to(ActionStatus.CANCELLED)
    assert ActionStatus.APPROVED.can_transition_to(ActionStatus.EXECUTING)
    assert ActionStatus.EXECUTING.can_transition_to(ActionStatus.NEEDS_REVIEW)

    with pytest.raises(InvalidActionTransition):
        ActionStatus.SUCCEEDED.require_transition(ActionStatus.EXECUTING)


def test_approval_terminal_status_rejects_transition() -> None:
    assert ApprovalStatus.PENDING.can_transition_to(ApprovalStatus.EXPIRED)

    with pytest.raises(InvalidApprovalTransition):
        ApprovalStatus.DENIED.require_transition(ApprovalStatus.APPROVED)
