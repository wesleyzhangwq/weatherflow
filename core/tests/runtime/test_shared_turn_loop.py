from pathlib import Path

from weatherflow.capabilities import (
    CapabilityCatalog,
    CapabilityResolver,
    CapabilitySnapshotCoordinator,
    CapabilitySnapshotRepository,
    ToolEffect,
    ToolSpec,
)
from weatherflow.events import EventLedger
from weatherflow.runs import RunCoordinator, RunRepository, RunStatus
from weatherflow.runtime import (
    AgentDefinition,
    FinalTurn,
    LoopStatus,
    RunCheckpointRepository,
    SharedTurnLoop,
    ToolCallTurn,
    ToolExecutionResult,
    ToolExecutorRegistry,
)
from weatherflow.storage import Database
from weatherflow.trust import SupervisedPolicy
from weatherflow.workspaces import Workspace


class ScriptedModel:
    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return self.turns.pop(0)


class RecordingExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, tool, arguments, context):
        self.calls.append((tool, arguments, context))
        return ToolExecutionResult(output={"content": "README contents"})


def spec(tool_id: str = "files.read") -> ToolSpec:
    return ToolSpec(
        tool_id=tool_id,
        description="Read file",
        input_schema={},
        output_schema={},
        effect=ToolEffect.OBSERVE,
        source="test",
        source_version="1",
    )


async def setup_loop(tmp_path: Path, model, *, tools=None, max_steps=5):
    tools = tools or (spec(),)
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    ledger = EventLedger(database)
    runs = RunRepository(database)
    run_coordinator = RunCoordinator(database, runs, ledger)
    run = await run_coordinator.create_run(
        client_request_id="request-1",
        user_intent="Read README and answer",
        workspace_id="workspace-1",
    )
    workspace = Workspace.new(
        name="WeatherFlow",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
    )
    snapshots = CapabilitySnapshotRepository(database)
    frozen = await CapabilitySnapshotCoordinator(
        database=database,
        snapshots=snapshots,
        runs=runs,
        ledger=ledger,
        resolver=CapabilityResolver(SupervisedPolicy()),
    ).freeze_for_run(
        run_id=run.id,
        expected_run_version=run.version,
        catalog=CapabilityCatalog(tools),
        catalog_revision="revision-1",
        workspace=workspace,
        requested_tool_ids={item.tool_id for item in tools},
    )
    executors = ToolExecutorRegistry()
    loop = SharedTurnLoop(
        database=database,
        runs=runs,
        run_coordinator=run_coordinator,
        checkpoints=RunCheckpointRepository(database),
        snapshots=snapshots,
        ledger=ledger,
        model=model,
        executors=executors,
        policy=SupervisedPolicy(),
    )
    agent = AgentDefinition(
        agent_id="orchestrator",
        system_prompt="Complete the goal",
        max_steps=max_steps,
    )
    return loop, executors, runs, loop.checkpoints, workspace, agent, frozen.run


async def test_final_answer_completes_run_and_checkpoint(tmp_path: Path) -> None:
    model = ScriptedModel([FinalTurn(content="The answer")])
    loop, _, runs, checkpoints, workspace, agent, run = await setup_loop(tmp_path, model)

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert outcome.status is LoopStatus.SUCCEEDED
    assert outcome.result_summary == "The answer"
    stored = await runs.get(run.id)
    checkpoint = await checkpoints.get(run.id)
    assert stored is not None and stored.status is RunStatus.SUCCEEDED
    assert checkpoint is not None
    assert checkpoint.transcript[-1].content == "The answer"
    assert checkpoint.state == {"result_committed": True}


async def test_safe_tool_result_is_observed_before_final_turn(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ToolCallTurn(tool_id="files.read", arguments={"path": "README.md"}),
            FinalTurn(content="Summarized"),
        ]
    )
    loop, executors, _, _, workspace, agent, run = await setup_loop(tmp_path, model)
    executor = RecordingExecutor()
    executors.register("files.read", executor)

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert outcome.status is LoopStatus.SUCCEEDED
    assert len(executor.calls) == 1
    assert "README contents" in model.requests[-1].messages[-1].content


async def test_tool_outside_snapshot_becomes_observation(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ToolCallTurn(tool_id="missing", arguments={}),
            FinalTurn(content="Recovered"),
        ]
    )
    loop, _, _, _, workspace, agent, run = await setup_loop(tmp_path, model)

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert outcome.status is LoopStatus.SUCCEEDED
    assert "not in frozen capability snapshot" in model.requests[-1].messages[-1].content


async def test_step_budget_exhaustion_fails_run(tmp_path: Path) -> None:
    model = ScriptedModel([ToolCallTurn(tool_id="files.read", arguments={})])
    loop, executors, runs, _, workspace, agent, run = await setup_loop(tmp_path, model, max_steps=1)
    executors.register("files.read", RecordingExecutor())

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert outcome.status is LoopStatus.FAILED
    stored = await runs.get(run.id)
    assert stored is not None and stored.status is RunStatus.FAILED
