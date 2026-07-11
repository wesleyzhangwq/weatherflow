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
    ActionExecutionCoordinator,
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
from weatherflow.trust import (
    ActionRepository,
    ActionStatus,
    ApprovalCoordinator,
    ApprovalRepository,
    SupervisedPolicy,
)
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
        granted_scopes={scope for item in tools for scope in item.required_scopes},
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
    approval_coordinator = ApprovalCoordinator(
        database=database,
        actions=ActionRepository(database),
        approvals=ApprovalRepository(database),
        runs=runs,
        run_coordinator=run_coordinator,
        ledger=ledger,
        policy=SupervisedPolicy(),
    )
    action_execution = ActionExecutionCoordinator(
        database=database,
        actions=approval_coordinator.actions,
        runs=runs,
        run_coordinator=run_coordinator,
        ledger=ledger,
        policy=SupervisedPolicy(),
    )
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
        approval_coordinator=approval_coordinator,
        action_execution=action_execution,
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


async def test_external_write_parks_once_without_executor_call(tmp_path: Path) -> None:
    external = ToolSpec(
        tool_id="github.create_release",
        description="Create release",
        input_schema={},
        output_schema={},
        effect=ToolEffect.EXTERNAL_WRITE,
        required_scopes=frozenset({"github:write"}),
        source="test",
        source_version="1",
    )
    model = ScriptedModel(
        [
            ToolCallTurn(
                call_id="release-v3",
                tool_id="github.create_release",
                arguments={"tag": "v3.0.0"},
            )
        ]
    )
    loop, executors, runs, checkpoints, workspace, agent, run = await setup_loop(
        tmp_path, model, tools=(external,)
    )
    workspace = workspace.model_copy(update={"granted_scopes": frozenset({"github:write"})})
    executor = RecordingExecutor()
    executors.register("github.create_release", executor)

    first = await loop.run(run_id=run.id, workspace=workspace, agent=agent)
    before = await loop.ledger.list_correlation(run.id)
    repeated = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert first.status is LoopStatus.WAITING_APPROVAL
    assert repeated == first
    assert executor.calls == []
    assert len(model.requests) == 1
    stored = await runs.get(run.id)
    checkpoint = await checkpoints.get(run.id)
    assert stored is not None and stored.status is RunStatus.WAITING_APPROVAL
    assert checkpoint is not None and checkpoint.pending_action_id == first.action_id
    assert await loop.ledger.list_correlation(run.id) == before


async def test_approved_action_executes_once_then_loop_finishes(tmp_path: Path) -> None:
    external = ToolSpec(
        tool_id="github.create_release",
        description="Create release",
        input_schema={},
        output_schema={},
        effect=ToolEffect.EXTERNAL_WRITE,
        required_scopes=frozenset({"github:write"}),
        source="test",
        source_version="1",
    )
    model = ScriptedModel(
        [
            ToolCallTurn(
                call_id="release-v3",
                tool_id="github.create_release",
                arguments={"tag": "v3.0.0"},
            ),
            FinalTurn(content="Release shipped"),
        ]
    )
    loop, executors, _, checkpoints, workspace, agent, run = await setup_loop(
        tmp_path, model, tools=(external,)
    )
    executor = RecordingExecutor()
    executors.register("github.create_release", executor)
    waiting = await loop.run(run_id=run.id, workspace=workspace, agent=agent)
    assert loop.approval_coordinator is not None
    await loop.approval_coordinator.decide(
        approval_id=waiting.approval_id,
        expected_version=0,
        approved=True,
        decided_by="user",
    )

    completed = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert completed.status is LoopStatus.SUCCEEDED
    assert len(executor.calls) == 1
    checkpoint = await checkpoints.get(run.id)
    assert checkpoint is not None and checkpoint.pending_action_id is None


async def test_denied_action_becomes_observation_without_execution(tmp_path: Path) -> None:
    external = ToolSpec(
        tool_id="github.create_release",
        description="Create release",
        input_schema={},
        output_schema={},
        effect=ToolEffect.EXTERNAL_WRITE,
        source="test",
        source_version="1",
    )
    model = ScriptedModel(
        [
            ToolCallTurn(tool_id=external.tool_id, arguments={}),
            FinalTurn(content="Continued without release"),
        ]
    )
    loop, executors, _, _, workspace, agent, run = await setup_loop(
        tmp_path, model, tools=(external,)
    )
    executor = RecordingExecutor()
    executors.register(external.tool_id, executor)
    waiting = await loop.run(run_id=run.id, workspace=workspace, agent=agent)
    assert loop.approval_coordinator is not None
    await loop.approval_coordinator.decide(
        approval_id=waiting.approval_id,
        expected_version=0,
        approved=False,
        decided_by="user",
    )

    completed = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert completed.status is LoopStatus.SUCCEEDED
    assert executor.calls == []
    assert "action denied" in model.requests[-1].messages[-1].content


async def test_executing_recovery_needs_review_without_model_retry(tmp_path: Path) -> None:
    external = ToolSpec(
        tool_id="github.create_release",
        description="Create release",
        input_schema={},
        output_schema={},
        effect=ToolEffect.EXTERNAL_WRITE,
        source="test",
        source_version="1",
    )
    model = ScriptedModel([ToolCallTurn(tool_id=external.tool_id, arguments={})])
    loop, executors, _, _, workspace, agent, run = await setup_loop(
        tmp_path, model, tools=(external,)
    )
    executor = RecordingExecutor()
    executors.register(external.tool_id, executor)
    waiting = await loop.run(run_id=run.id, workspace=workspace, agent=agent)
    assert loop.approval_coordinator is not None
    await loop.approval_coordinator.decide(
        approval_id=waiting.approval_id,
        expected_version=0,
        approved=True,
        decided_by="user",
    )
    action = await loop.approval_coordinator.actions.get(waiting.action_id)
    assert action is not None
    async with loop.database.transaction() as connection:
        await loop.approval_coordinator.actions.transition_in(
            connection, action.id, ActionStatus.EXECUTING, action.version
        )

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert outcome.status is LoopStatus.NEEDS_REVIEW
    assert len(model.requests) == 1
    assert executor.calls == []
