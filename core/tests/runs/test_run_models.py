import pytest

from weatherflow.runs import InvalidTransitionError, Run, RunStatus


def test_new_run_is_queued_with_zero_version() -> None:
    run = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )

    assert run.status is RunStatus.QUEUED
    assert run.version == 0
    assert len(run.id) == 26


@pytest.mark.parametrize("target", [RunStatus.PLANNING, RunStatus.CANCELLED])
def test_queued_run_allows_declared_transitions(target: RunStatus) -> None:
    assert RunStatus.QUEUED.can_transition_to(target)


def test_terminal_run_rejects_transition() -> None:
    with pytest.raises(InvalidTransitionError):
        RunStatus.SUCCEEDED.require_transition(RunStatus.RUNNING)


def test_waiting_approval_can_suspend_on_timeout() -> None:
    assert RunStatus.WAITING_APPROVAL.can_transition_to(RunStatus.PAUSED)
