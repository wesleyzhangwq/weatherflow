from datetime import UTC, datetime
from pathlib import Path

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.rhythm import CheckInSignal
from weatherflow.runtime import FinalTurn


class CapturingModel:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return FinalTurn(content="Release preparation complete")


async def test_run_binds_overload_policy_without_changing_explicit_goal(
    tmp_path: Path,
) -> None:
    model = CapturingModel()
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path), model=model)
    current = await container.rhythm.ingest(
        container.default_workspace.id,
        CheckInSignal(
            text="I am overloaded and exhausted, but this release must ship",
            observed_at=datetime.now(UTC),
        ),
    )
    goal = "Ship this version with the least additional burden"

    run, outcome = await container.submit_run(
        user_intent=goal,
        client_request_id="flagship-request",
    )

    assert outcome is not None and outcome.result_summary == "Release preparation complete"
    stored = await container.runs.get(run.id)
    assert stored is not None and stored.rhythm_snapshot_id == current.snapshot.id
    request = model.requests[0]
    assert request.messages[0].content == goal
    assert "interaction_budget=minimal" in request.agent.system_prompt
    assert "delegation_bias=favor" in request.agent.system_prompt
    assert "scope_pressure=reduce" in request.agent.system_prompt
    assert "never changes the explicit user goal" in request.agent.system_prompt
    checkpoint = await container.checkpoints.get(run.id)
    assert checkpoint is not None
    assert checkpoint.state["rhythm_policy"]["proactivity"] == "silent"
    events = await container.ledger.list_correlation(run.id, limit=1000)
    assert [event.type for event in events].count("run.rhythm_policy_bound") == 1
    assert [event.type for event in events].count("rhythm.signal.task_behavior") == 1

    repeated, _ = await container.submit_run(
        user_intent="A retry must not replace the goal",
        client_request_id="flagship-request",
    )
    repeated_events = await container.ledger.list_correlation(run.id, limit=1000)
    assert repeated.id == run.id
    assert [event.type for event in repeated_events].count("run.rhythm_policy_bound") == 1
    assert [event.type for event in repeated_events].count("rhythm.signal.task_behavior") == 1


async def test_missing_current_evidence_binds_safe_normal_fallback(tmp_path: Path) -> None:
    model = CapturingModel()
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path), model=model)

    run, _ = await container.submit_run(user_intent="Explain the repository")

    stored = await container.runs.get(run.id)
    assert stored is not None and stored.rhythm_snapshot_id is not None
    prompt = model.requests[0].agent.system_prompt
    assert "interaction_budget=normal" in prompt
    assert "delegation_bias=neutral" in prompt
    assert "proactivity=silent" in prompt
