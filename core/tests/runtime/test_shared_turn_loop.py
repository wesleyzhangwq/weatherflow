import asyncio
import threading
from pathlib import Path

import pytest

from weatherflow.capabilities import (
    CapabilityCatalog,
    CapabilityResolver,
    CapabilitySnapshotCoordinator,
    CapabilitySnapshotRepository,
    ToolEffect,
    ToolSpec,
)
from weatherflow.events import EventLedger
from weatherflow.runs import RunBudget, RunCoordinator, RunRepository, RunStatus
from weatherflow.runtime import (
    ActionExecutionCoordinator,
    ActionExecutionStatus,
    AgentDefinition,
    FinalTurn,
    LoopStatus,
    RunCheckpointRepository,
    SharedTurnLoop,
    ToolCallBatchTurn,
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


class BlockingExecutor:
    async def execute(self, tool, arguments, context):
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class ThreadedSideEffectExecutor:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.completed = threading.Event()

    async def execute(self, tool, arguments, context):
        def side_effect() -> None:
            self.started.set()
            self.release.wait(timeout=5)
            self.completed.set()

        await asyncio.to_thread(side_effect)
        return ToolExecutionResult(output={"written": True})


class InvalidSafeOutputExecutor:
    def __init__(self) -> None:
        self.calls = []

    async def execute(self, tool, arguments, context):
        self.calls.append((tool, arguments, context))
        return ToolExecutionResult(
            output={"content": 42, "credential": "must-not-enter-checkpoint"}
        )


class FailingSafeExecutor:
    async def execute(self, tool, arguments, context):
        del tool, arguments, context
        raise RuntimeError("request failed with sk-must-not-enter-model-context")


def object_schema(
    properties: dict[str, object],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def spec(tool_id: str = "files.read") -> ToolSpec:
    return ToolSpec(
        tool_id=tool_id,
        description="Read file",
        input_schema=object_schema({"path": {"type": "string"}}),
        output_schema=object_schema(
            {"content": {"type": "string"}},
            required=("content",),
        ),
        effect=ToolEffect.OBSERVE,
        source="test",
        source_version="1",
    )


async def setup_loop(tmp_path: Path, model, *, tools=None, max_steps=5, budget=None):
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
        budget=budget,
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


async def test_ordered_tool_batch_observes_every_result_before_next_model_turn(
    tmp_path: Path,
) -> None:
    model = ScriptedModel(
        [
            ToolCallBatchTurn(
                calls=(
                    ToolCallTurn(tool_id="files.read", arguments={"path": "A.md"}),
                    ToolCallTurn(tool_id="files.read", arguments={"path": "B.md"}),
                )
            ),
            FinalTurn(content="Both files were read"),
        ]
    )
    loop, executors, _, checkpoints, workspace, agent, run = await setup_loop(tmp_path, model)
    executor = RecordingExecutor()
    executors.register("files.read", executor)

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert outcome.status is LoopStatus.SUCCEEDED
    assert [call[1]["path"] for call in executor.calls] == ["A.md", "B.md"]
    assert len(model.requests[-1].messages) >= 4
    checkpoint = await checkpoints.get(run.id)
    assert checkpoint is not None
    assert "batch_next_index" not in checkpoint.state


async def test_cost_budget_stops_before_dispatching_an_over_budget_tool(
    tmp_path: Path,
) -> None:
    model = ScriptedModel(
        [
            ToolCallTurn(
                tool_id="files.read",
                arguments={"path": "README.md"},
                usage={"input_tokens": 10, "output_tokens": 2, "cost_usd": 0.51},
            )
        ]
    )
    loop, executors, runs, checkpoints, workspace, agent, run = await setup_loop(
        tmp_path,
        model,
        budget=RunBudget(max_steps=5, max_cost_usd=0.50, timeout_seconds=60),
    )
    executor = RecordingExecutor()
    executors.register("files.read", executor)

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert outcome.status is LoopStatus.FAILED
    assert outcome.error == "run cost budget exhausted"
    assert executor.calls == []
    checkpoint = await checkpoints.get(run.id)
    assert checkpoint is not None
    assert checkpoint.state["runtime_usage"] == {
        "input_tokens": 10,
        "output_tokens": 2,
        "cost_usd": 0.51,
        "cost_status": "known",
    }
    stored = await runs.get(run.id)
    assert stored is not None and stored.status is RunStatus.FAILED


async def test_unknown_model_cost_fails_closed_before_tool_dispatch(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ToolCallTurn(
                tool_id="files.read",
                arguments={"path": "README.md"},
                usage={"input_tokens": 10, "output_tokens": 2},
            )
        ]
    )
    loop, executors, runs, checkpoints, workspace, agent, run = await setup_loop(
        tmp_path,
        model,
        budget=RunBudget(max_steps=5, max_cost_usd=1.0, timeout_seconds=60),
    )
    executor = RecordingExecutor()
    executors.register("files.read", executor)

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert outcome.status is LoopStatus.FAILED
    assert outcome.error == "run cost budget cannot be enforced: model cost is unknown"
    assert executor.calls == []
    checkpoint = await checkpoints.get(run.id)
    assert checkpoint is not None
    assert checkpoint.state["runtime_usage"]["cost_status"] == "unknown"
    stored = await runs.get(run.id)
    assert stored is not None and stored.status is RunStatus.FAILED


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


async def test_missing_required_tool_arguments_are_rejected_before_execution(
    tmp_path: Path,
) -> None:
    read_tool = ToolSpec(
        tool_id="files.read",
        description="Read file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        output_schema={},
        effect=ToolEffect.OBSERVE,
        source="test",
        source_version="1",
    )
    model = ScriptedModel(
        [
            ToolCallTurn(tool_id="files.read", arguments={}),
            FinalTurn(content="Recovered after validation"),
        ]
    )
    loop, executors, _, _, workspace, agent, run = await setup_loop(
        tmp_path, model, tools=(read_tool,)
    )
    executor = RecordingExecutor()
    executors.register("files.read", executor)

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert outcome.status is LoopStatus.SUCCEEDED
    assert executor.calls == []
    assert "Missing: path" in model.requests[-1].messages[-1].content


@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": "ten", "kind": "open"},
        {"limit": 10, "kind": "unknown"},
        {"limit": 10, "kind": "open", "unexpected": True},
    ],
)
async def test_full_json_schema_rejects_invalid_tool_arguments_before_execution(
    tmp_path: Path,
    arguments: dict[str, object],
) -> None:
    search_tool = ToolSpec(
        tool_id="issues.search",
        description="Search issues",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "kind": {"type": "string", "enum": ["open", "closed"]},
            },
            "required": ["limit", "kind"],
            "additionalProperties": False,
        },
        output_schema={},
        effect=ToolEffect.NETWORK_READ,
        source="test",
        source_version="1",
    )
    model = ScriptedModel(
        [
            ToolCallTurn(tool_id=search_tool.tool_id, arguments=arguments),
            FinalTurn(content="Recovered after validation"),
        ]
    )
    loop, executors, _, _, workspace, agent, run = await setup_loop(
        tmp_path, model, tools=(search_tool,)
    )
    executor = RecordingExecutor()
    executors.register(search_tool.tool_id, executor)

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert outcome.status is LoopStatus.SUCCEEDED
    assert executor.calls == []
    assert "invalid_tool_arguments" in model.requests[-1].messages[-1].content


async def test_safe_tool_timeout_is_observed_and_loop_can_continue(tmp_path: Path) -> None:
    slow_tool = spec().model_copy(update={"timeout_seconds": 1})
    model = ScriptedModel(
        [
            ToolCallTurn(tool_id=slow_tool.tool_id, arguments={}),
            FinalTurn(content="Continued after timeout"),
        ]
    )
    loop, executors, _, _, workspace, agent, run = await setup_loop(
        tmp_path, model, tools=(slow_tool,)
    )
    executors.register(slow_tool.tool_id, BlockingExecutor())

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert outcome.status is LoopStatus.SUCCEEDED
    assert "tool_timeout" in model.requests[-1].messages[-1].content


async def test_safe_tool_exception_is_redacted_before_checkpoint_and_model_context(
    tmp_path: Path,
) -> None:
    read_tool = spec()
    model = ScriptedModel(
        [
            ToolCallTurn(tool_id=read_tool.tool_id, arguments={}),
            FinalTurn(content="Recovered after safe failure"),
        ]
    )
    loop, executors, _, checkpoints, workspace, agent, run = await setup_loop(
        tmp_path,
        model,
        tools=(read_tool,),
    )
    executors.register(read_tool.tool_id, FailingSafeExecutor())

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    checkpoint = await checkpoints.get(run.id)
    assert outcome.status is LoopStatus.SUCCEEDED
    assert "sk-must-not-enter-model-context" not in model.requests[-1].messages[-1].content
    assert checkpoint is not None
    assert "sk-must-not-enter-model-context" not in str(checkpoint.transcript)


async def test_safe_tool_invalid_output_is_replaced_before_checkpoint_and_model_context(
    tmp_path: Path,
) -> None:
    read_tool = spec()
    model = ScriptedModel(
        [
            ToolCallTurn(tool_id=read_tool.tool_id, arguments={}),
            FinalTurn(content="Recovered after invalid output"),
        ]
    )
    loop, executors, _, checkpoints, workspace, agent, run = await setup_loop(
        tmp_path,
        model,
        tools=(read_tool,),
    )
    executor = InvalidSafeOutputExecutor()
    executors.register(read_tool.tool_id, executor)

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert outcome.status is LoopStatus.SUCCEEDED
    assert len(executor.calls) == 1
    model_observation = model.requests[-1].messages[-1].content
    assert "invalid_tool_output" in model_observation
    assert "credential" not in model_observation
    assert "must-not-enter-checkpoint" not in model_observation
    checkpoint = await checkpoints.get(run.id)
    assert checkpoint is not None
    assert "must-not-enter-checkpoint" not in str(checkpoint.transcript)


@pytest.mark.parametrize("effect", [ToolEffect.WORKSPACE_WRITE, ToolEffect.EXECUTE])
async def test_sandboxed_side_effect_timeout_creates_durable_review_barrier(
    tmp_path: Path,
    effect: ToolEffect,
) -> None:
    side_effect = ToolSpec(
        tool_id=f"sandbox.{effect.value}",
        description="Perform one sandboxed side effect",
        input_schema={},
        output_schema={},
        effect=effect,
        timeout_seconds=1,
        source="test",
        source_version="1",
    )
    model = ScriptedModel(
        [
            ToolCallTurn(tool_id=side_effect.tool_id, arguments={}),
            FinalTurn(content="must not reach final"),
        ]
    )
    loop, executors, runs, _, workspace, agent, run = await setup_loop(
        tmp_path,
        model,
        tools=(side_effect,),
    )
    executor = ThreadedSideEffectExecutor()
    executors.register(side_effect.tool_id, executor)

    try:
        outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)
        assert executor.started.is_set()
        assert not executor.completed.is_set()
    finally:
        executor.release.set()
        await asyncio.to_thread(executor.completed.wait, 1)

    assert outcome.status is LoopStatus.NEEDS_REVIEW
    assert outcome.action_id is not None
    assert len(model.requests) == 1
    action = await loop.approval_coordinator.actions.get(outcome.action_id)
    assert action is not None and action.status is ActionStatus.NEEDS_REVIEW
    stored = await runs.get(run.id)
    assert stored is not None and stored.status is RunStatus.NEEDS_REVIEW


async def test_cancelling_sandboxed_to_thread_tool_records_review_before_propagating(
    tmp_path: Path,
) -> None:
    side_effect = ToolSpec(
        tool_id="sandbox.write",
        description="Perform one sandboxed side effect",
        input_schema={},
        output_schema={},
        effect=ToolEffect.WORKSPACE_WRITE,
        timeout_seconds=30,
        source="test",
        source_version="1",
    )
    model = ScriptedModel([ToolCallTurn(tool_id=side_effect.tool_id, arguments={})])
    loop, executors, runs, _, workspace, agent, run = await setup_loop(
        tmp_path,
        model,
        tools=(side_effect,),
    )
    executor = ThreadedSideEffectExecutor()
    executors.register(side_effect.tool_id, executor)
    execution = asyncio.create_task(loop.run(run_id=run.id, workspace=workspace, agent=agent))
    await asyncio.to_thread(executor.started.wait, 1)

    execution.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await execution
        assert not executor.completed.is_set()
    finally:
        executor.release.set()
        await asyncio.to_thread(executor.completed.wait, 1)

    events = await loop.ledger.list_correlation(run.id)
    action_event = next(event for event in events if event.type == "action.proposed")
    action = await loop.approval_coordinator.actions.get(action_event.stream_id)
    assert action is not None and action.status is ActionStatus.NEEDS_REVIEW
    stored = await runs.get(run.id)
    assert stored is not None and stored.status is RunStatus.NEEDS_REVIEW


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


async def test_mixed_batch_resumes_at_approved_call_without_replaying_prior_read(
    tmp_path: Path,
) -> None:
    read = spec("files.read")
    write = ToolSpec(
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
            ToolCallBatchTurn(
                calls=(
                    ToolCallTurn(
                        call_id="read-first",
                        tool_id=read.tool_id,
                        arguments={"path": "README.md"},
                    ),
                    ToolCallTurn(
                        call_id="write-second",
                        tool_id=write.tool_id,
                        arguments={"tag": "v3.0.0"},
                    ),
                )
            ),
            FinalTurn(content="Read and release completed"),
        ]
    )
    loop, executors, _, _, workspace, agent, run = await setup_loop(
        tmp_path, model, tools=(read, write)
    )
    executor = RecordingExecutor()
    executors.register(read.tool_id, executor)
    executors.register(write.tool_id, executor)

    waiting = await loop.run(run_id=run.id, workspace=workspace, agent=agent)
    assert waiting.status is LoopStatus.WAITING_APPROVAL
    assert [call[0].tool_id for call in executor.calls] == [read.tool_id]
    assert loop.approval_coordinator is not None
    await loop.approval_coordinator.decide(
        approval_id=waiting.approval_id,
        expected_version=0,
        approved=True,
        decided_by="user",
    )

    completed = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert completed.status is LoopStatus.SUCCEEDED
    assert [call[0].tool_id for call in executor.calls] == [read.tool_id, write.tool_id]


async def test_duplicate_provider_call_ids_in_batch_create_distinct_actions(
    tmp_path: Path,
) -> None:
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
            ToolCallBatchTurn(
                calls=(
                    ToolCallTurn(
                        call_id="provider-reused-id",
                        tool_id=external.tool_id,
                        arguments={"tag": "v3.0.0"},
                    ),
                    ToolCallTurn(
                        call_id="provider-reused-id",
                        tool_id=external.tool_id,
                        arguments={"tag": "v3.0.0"},
                    ),
                )
            ),
            FinalTurn(content="Both releases completed"),
        ]
    )
    loop, executors, _, _, workspace, agent, run = await setup_loop(
        tmp_path, model, tools=(external,)
    )
    executor = RecordingExecutor()
    executors.register(external.tool_id, executor)
    assert loop.approval_coordinator is not None

    first = await loop.run(run_id=run.id, workspace=workspace, agent=agent)
    await loop.approval_coordinator.decide(
        approval_id=first.approval_id,
        expected_version=0,
        approved=True,
        decided_by="user",
    )
    second = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert second.status is LoopStatus.WAITING_APPROVAL
    assert second.action_id != first.action_id
    assert [call[1]["tag"] for call in executor.calls] == ["v3.0.0"]

    await loop.approval_coordinator.decide(
        approval_id=second.approval_id,
        expected_version=0,
        approved=True,
        decided_by="user",
    )
    completed = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert completed.status is LoopStatus.SUCCEEDED
    assert [call[1]["tag"] for call in executor.calls] == ["v3.0.0", "v3.0.0"]


async def test_succeeded_action_result_is_recovered_without_replaying_side_effect(
    tmp_path: Path,
) -> None:
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
                tool_id=external.tool_id,
                arguments={"tag": "v3.0.0"},
            ),
            FinalTurn(content="Recovered the completed release"),
        ]
    )
    loop, executors, _, checkpoints, workspace, agent, run = await setup_loop(
        tmp_path, model, tools=(external,)
    )
    executor = RecordingExecutor()
    executors.register(external.tool_id, executor)
    assert loop.approval_coordinator is not None
    assert loop.action_execution is not None
    waiting = await loop.run(run_id=run.id, workspace=workspace, agent=agent)
    decided = await loop.approval_coordinator.decide(
        approval_id=waiting.approval_id,
        expected_version=0,
        approved=True,
        decided_by="user",
    )

    executed = await loop.action_execution.execute(
        action_id=decided.action.id,
        tool=external,
        workspace=workspace,
        executor=executor,
    )
    checkpoint_before_recovery = await checkpoints.get(run.id)
    assert executed.status is ActionExecutionStatus.SUCCEEDED
    assert checkpoint_before_recovery is not None
    assert checkpoint_before_recovery.pending_action_id == waiting.action_id

    completed = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert completed.status is LoopStatus.SUCCEEDED
    assert len(executor.calls) == 1
    assert "README contents" in model.requests[-1].messages[-1].content
    checkpoint = await checkpoints.get(run.id)
    assert checkpoint is not None and checkpoint.pending_action_id is None


async def test_recovered_side_effect_with_invalid_output_needs_review_without_replay(
    tmp_path: Path,
) -> None:
    external = ToolSpec(
        tool_id="github.create_release",
        description="Create release",
        input_schema=object_schema({"tag": {"type": "string"}}),
        output_schema=object_schema(
            {"content": {"type": "string"}},
            required=("content",),
        ),
        effect=ToolEffect.EXTERNAL_WRITE,
        required_scopes=frozenset({"github:write"}),
        source="test",
        source_version="1",
    )
    model = ScriptedModel(
        [
            ToolCallTurn(
                call_id="release-v3-invalid-result",
                tool_id=external.tool_id,
                arguments={"tag": "v3.0.0"},
            ),
            FinalTurn(content="must not consume invalid output"),
        ]
    )
    loop, executors, runs, checkpoints, workspace, agent, run = await setup_loop(
        tmp_path,
        model,
        tools=(external,),
    )
    executor = RecordingExecutor()
    executors.register(external.tool_id, executor)
    assert loop.approval_coordinator is not None
    waiting = await loop.run(run_id=run.id, workspace=workspace, agent=agent)
    decided = await loop.approval_coordinator.decide(
        approval_id=waiting.approval_id,
        expected_version=0,
        approved=True,
        decided_by="user",
    )
    async with loop.database.transaction() as connection:
        executing = await loop.approval_coordinator.actions.transition_in(
            connection,
            decided.action.id,
            ActionStatus.EXECUTING,
            decided.action.version,
        )
        await loop.approval_coordinator.actions.transition_in(
            connection,
            executing.id,
            ActionStatus.SUCCEEDED,
            executing.version,
            result={"content": 42, "credential": "must-not-enter-checkpoint"},
        )

    outcome = await loop.run(run_id=run.id, workspace=workspace, agent=agent)

    assert outcome.status is LoopStatus.NEEDS_REVIEW
    assert outcome.action_id == decided.action.id
    assert executor.calls == []
    assert len(model.requests) == 1
    action = await loop.approval_coordinator.actions.get(decided.action.id)
    assert action is not None and action.status is ActionStatus.NEEDS_REVIEW
    assert action.result is None
    assert "must-not-enter-checkpoint" not in str(action)
    stored_run = await runs.get(run.id)
    assert stored_run is not None and stored_run.status is RunStatus.NEEDS_REVIEW
    checkpoint = await checkpoints.get(run.id)
    assert checkpoint is not None
    assert "must-not-enter-checkpoint" not in str(checkpoint.transcript)


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
