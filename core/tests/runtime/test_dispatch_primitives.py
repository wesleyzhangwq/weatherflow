import json

import pytest

from weatherflow.runtime import (
    BoundedObservation,
    DuplicateToolExecutor,
    LoopOutcome,
    LoopStatus,
    ToolExecutorNotFound,
    ToolExecutorRegistry,
)


class Executor:
    async def execute(self, tool, arguments, context):
        raise AssertionError("not called")


def test_executor_registry_rejects_duplicates_and_missing_ids() -> None:
    executor = Executor()
    registry = ToolExecutorRegistry()
    registry.register("files.read", executor)

    assert registry.get("files.read") is executor
    with pytest.raises(DuplicateToolExecutor):
        registry.register("files.read", executor)
    with pytest.raises(ToolExecutorNotFound):
        registry.require("missing")


def test_bounded_observation_preserves_structured_validity() -> None:
    observation = BoundedObservation.from_output({"content": "x" * 100}, max_chars=20)

    encoded = observation.model_dump_json()
    assert json.loads(encoded)
    assert observation.truncated
    assert len(observation.output["preview"]) == 20


@pytest.mark.parametrize(
    ("status", "values"),
    [
        (LoopStatus.SUCCEEDED, {"result_summary": "done"}),
        (
            LoopStatus.WAITING_APPROVAL,
            {"action_id": "action-1", "approval_id": "approval-1"},
        ),
        (LoopStatus.FAILED, {"error": "step budget exhausted"}),
    ],
)
def test_loop_outcomes_are_frozen(status: LoopStatus, values: dict[str, str]) -> None:
    outcome = LoopOutcome(run_id="run-1", status=status, **values)

    assert outcome.status is status
