from __future__ import annotations

from app.core.agent_runs import AgentRunTracker
from app.memory import dev_review_repo
from app.memory.schemas import AgentRunCreate


def test_tracker_marks_partial_when_any_step_is_not_success() -> None:
    run_id = dev_review_repo.create_run(
        AgentRunCreate(
            input={
                "window_days": 7,
                "providers": ["github", "google_calendar"],
            }
        )
    )

    tracker = AgentRunTracker(run_id)
    tracker.step("github", "success", "Found recent PR activity.")
    tracker.step("google_calendar", "skipped", "Calendar access is not configured.")
    run = tracker.finish()

    assert run.status == "partial"
    assert len(run.steps) == 2
    assert run.steps[1].status == "skipped"


def test_tracker_can_fail_run_with_error() -> None:
    run_id = dev_review_repo.create_run(
        AgentRunCreate(
            input={
                "window_days": 7,
                "providers": ["github", "google_calendar"],
            }
        )
    )

    tracker = AgentRunTracker(run_id)
    run = tracker.fail("No provider succeeded.")

    assert run.status == "failed"
    assert run.error == "No provider succeeded."
