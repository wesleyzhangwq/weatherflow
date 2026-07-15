import pytest
from pydantic import ValidationError

from weatherflow.runtime import (
    LoopOutcome,
    LoopStatus,
    RunCheckpoint,
    ToolDispatchResult,
)


def test_tool_dispatch_result_contains_exactly_one_durable_next_state() -> None:
    checkpoint = RunCheckpoint.new(run_id="run-1")
    outcome = LoopOutcome(run_id="run-1", status=LoopStatus.NEEDS_REVIEW)

    assert ToolDispatchResult.from_checkpoint(checkpoint).checkpoint == checkpoint
    assert ToolDispatchResult.from_outcome(outcome).outcome == outcome

    with pytest.raises(ValidationError):
        ToolDispatchResult()
    with pytest.raises(ValidationError):
        ToolDispatchResult(checkpoint=checkpoint, outcome=outcome)
