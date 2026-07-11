import json
from typing import Any

from pydantic import TypeAdapter

from weatherflow.capabilities import CapabilitySnapshotRepository, ToolSpec
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs import Run, RunCoordinator, RunRepository, RunStatus
from weatherflow.runtime.checkpoints import RunCheckpoint
from weatherflow.runtime.models import (
    AgentDefinition,
    AgentMessage,
    DelegationTurn,
    FinalTurn,
    MessageRole,
    ModelRequest,
    ModelTurn,
    ToolCallTurn,
    ToolExecutionContext,
)
from weatherflow.runtime.outcomes import BoundedObservation, LoopOutcome, LoopStatus
from weatherflow.runtime.protocols import ModelAdapter
from weatherflow.runtime.repository import RunCheckpointRepository
from weatherflow.runtime.tools import ToolExecutorNotFound, ToolExecutorRegistry
from weatherflow.storage import Database
from weatherflow.trust import DecisionKind, SupervisedPolicy
from weatherflow.workspaces import Workspace


class SharedTurnLoop:
    def __init__(
        self,
        *,
        database: Database,
        runs: RunRepository,
        run_coordinator: RunCoordinator,
        checkpoints: RunCheckpointRepository,
        snapshots: CapabilitySnapshotRepository,
        ledger: EventLedger,
        model: ModelAdapter,
        executors: ToolExecutorRegistry,
        policy: SupervisedPolicy,
    ) -> None:
        self.database = database
        self.runs = runs
        self.run_coordinator = run_coordinator
        self.checkpoints = checkpoints
        self.snapshots = snapshots
        self.ledger = ledger
        self.model = model
        self.executors = executors
        self.policy = policy

    async def run(
        self,
        *,
        run_id: str,
        workspace: Workspace,
        agent: AgentDefinition,
    ) -> LoopOutcome:
        run = await self._ensure_running(run_id)
        checkpoint = await self._ensure_checkpoint(run)
        snapshot = await self.snapshots.get_by_run_id(run_id)
        if snapshot is None:
            return await self._fail(run, checkpoint, "capability snapshot is missing")
        tools = tuple(
            tool
            for tool in snapshot.tools
            if not agent.tool_filter or tool.tool_id in agent.tool_filter
        )
        tool_map = {tool.tool_id: tool for tool in tools}
        step_limit = min(agent.max_steps, run.budget.max_steps)

        while True:
            pending = checkpoint.state.get("pending_turn")
            if pending is None:
                if checkpoint.step_index >= step_limit:
                    return await self._fail(run, checkpoint, "step budget exhausted")
                request = ModelRequest(
                    run_id=run_id,
                    agent=agent,
                    messages=checkpoint.transcript,
                    tools=tools,
                )
                turn = agent.validate_turn(await self.model.complete(request))
                checkpoint = await self._record_turn(checkpoint, turn)
            else:
                turn = TypeAdapter(ModelTurn).validate_python(pending)

            if isinstance(turn, FinalTurn):
                return await self._commit_final(run, checkpoint, turn.content)
            if isinstance(turn, ToolCallTurn):
                tool = tool_map.get(turn.tool_id)
                if tool is None:
                    checkpoint = await self._record_observation(
                        checkpoint,
                        turn,
                        {"error": f"{turn.tool_id} is not in frozen capability snapshot"},
                    )
                    continue
                decision = self.policy.evaluate(tool, workspace)
                if decision.kind in {DecisionKind.DENY, DecisionKind.HIDE}:
                    checkpoint = await self._record_observation(
                        checkpoint,
                        turn,
                        {"error": decision.reason, "decision": decision.kind.value},
                    )
                    continue
                if decision.kind is DecisionKind.APPROVE:
                    checkpoint = await self._record_observation(
                        checkpoint,
                        turn,
                        {"error": "approval dispatch is not configured"},
                    )
                    continue
                checkpoint = await self._execute_safe_tool(run, checkpoint, turn, tool)
                continue
            if isinstance(turn, DelegationTurn):
                checkpoint = await self._record_observation(
                    checkpoint,
                    turn,
                    {"error": "delegation runtime is not installed"},
                )

    async def _ensure_running(self, run_id: str) -> Run:
        run = await self.runs.get(run_id)
        if run is None:
            raise LookupError(run_id)
        if run.status is RunStatus.QUEUED:
            run = await self.run_coordinator.transition(
                run_id=run.id,
                target=RunStatus.PLANNING,
                expected_version=run.version,
            )
        if run.status is RunStatus.PLANNING:
            run = await self.run_coordinator.transition(
                run_id=run.id,
                target=RunStatus.RUNNING,
                expected_version=run.version,
            )
        if run.status is RunStatus.PAUSED:
            run = await self.run_coordinator.transition(
                run_id=run.id,
                target=RunStatus.RUNNING,
                expected_version=run.version,
            )
        if run.status is not RunStatus.RUNNING:
            raise RuntimeError(f"run {run.id} is {run.status.value}")
        return run

    async def _ensure_checkpoint(self, run: Run) -> RunCheckpoint:
        existing = await self.checkpoints.get(run.id)
        if existing is not None:
            return existing
        checkpoint = RunCheckpoint.new(
            run_id=run.id,
            transcript=(AgentMessage(role=MessageRole.USER, content=run.user_intent),),
        )
        async with self.database.transaction() as connection:
            existing = await self.checkpoints.get_in(connection, run.id)
            if existing is not None:
                return existing
            await self.checkpoints.create_in(connection, checkpoint)
        return checkpoint

    async def _record_turn(self, checkpoint: RunCheckpoint, turn: ModelTurn) -> RunCheckpoint:
        message = self._turn_message(turn)
        state = dict(checkpoint.state)
        state["pending_turn"] = turn.model_dump(mode="json")
        desired = checkpoint.model_copy(
            update={
                "step_index": checkpoint.step_index + 1,
                "transcript": (*checkpoint.transcript, message),
                "state": state,
            }
        )
        async with self.database.transaction() as connection:
            saved = await self.checkpoints.save_in(
                connection, desired, expected_version=checkpoint.version
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="runtime.turn_recorded",
                    actor=Actor.AGENT,
                    stream_kind="run",
                    stream_id=checkpoint.run_id,
                    correlation_id=checkpoint.run_id,
                    payload={"kind": turn.kind, "step_index": saved.step_index},
                ),
            )
        return saved

    async def _execute_safe_tool(
        self,
        run: Run,
        checkpoint: RunCheckpoint,
        turn: ToolCallTurn,
        tool: ToolSpec,
    ) -> RunCheckpoint:
        try:
            executor = self.executors.require(tool.tool_id)
            result = await executor.execute(
                tool,
                turn.arguments,
                ToolExecutionContext(run_id=run.id, workspace_id=run.workspace_id),
            )
            output = result.output
        except ToolExecutorNotFound:
            output = {"error": f"no executor registered for {tool.tool_id}"}
        except Exception as error:
            output = {"error": type(error).__name__, "message": str(error)}
        return await self._record_observation(checkpoint, turn, output)

    async def _record_observation(
        self,
        checkpoint: RunCheckpoint,
        turn: ToolCallTurn | DelegationTurn,
        output: dict[str, Any],
    ) -> RunCheckpoint:
        observation = BoundedObservation.from_output(output)
        state = dict(checkpoint.state)
        state.pop("pending_turn", None)
        desired = checkpoint.model_copy(
            update={
                "transcript": (
                    *checkpoint.transcript,
                    AgentMessage(
                        role=MessageRole.TOOL,
                        name=turn.tool_id if isinstance(turn, ToolCallTurn) else turn.agent_id,
                        tool_call_id=turn.call_id if isinstance(turn, ToolCallTurn) else None,
                        content=json.dumps(
                            observation.output,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    ),
                ),
                "state": state,
            }
        )
        async with self.database.transaction() as connection:
            saved = await self.checkpoints.save_in(
                connection, desired, expected_version=checkpoint.version
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="tool.executed",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=checkpoint.run_id,
                    correlation_id=checkpoint.run_id,
                    payload={
                        "target": turn.tool_id if isinstance(turn, ToolCallTurn) else turn.agent_id,
                        "truncated": observation.truncated,
                    },
                ),
            )
        return saved

    async def _commit_final(self, run: Run, checkpoint: RunCheckpoint, content: str) -> LoopOutcome:
        state = dict(checkpoint.state)
        state.pop("pending_turn", None)
        state["result_committed"] = True
        desired = checkpoint.model_copy(update={"state": state})
        current_run = await self.runs.get(run.id)
        if current_run is None:
            raise LookupError(run.id)
        async with self.database.transaction() as connection:
            await self.checkpoints.save_in(connection, desired, expected_version=checkpoint.version)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="run.result_committed",
                    actor=Actor.AGENT,
                    stream_kind="run",
                    stream_id=run.id,
                    correlation_id=run.id,
                    payload={"summary": content},
                ),
            )
            await self.run_coordinator.transition_in(
                connection,
                run_id=run.id,
                target=RunStatus.SUCCEEDED,
                expected_version=current_run.version,
                result_summary=content,
            )
        return LoopOutcome(
            run_id=run.id,
            status=LoopStatus.SUCCEEDED,
            result_summary=content,
        )

    async def _fail(self, run: Run, checkpoint: RunCheckpoint, error: str) -> LoopOutcome:
        state = dict(checkpoint.state)
        state.pop("pending_turn", None)
        state["error"] = error
        desired = checkpoint.model_copy(update={"state": state})
        current_run = await self.runs.get(run.id)
        if current_run is None:
            raise LookupError(run.id)
        async with self.database.transaction() as connection:
            await self.checkpoints.save_in(connection, desired, expected_version=checkpoint.version)
            await self.run_coordinator.transition_in(
                connection,
                run_id=run.id,
                target=RunStatus.FAILED,
                expected_version=current_run.version,
                error_class="RuntimeLimitError",
                error_message=error,
            )
        return LoopOutcome(run_id=run.id, status=LoopStatus.FAILED, error=error)

    @staticmethod
    def _turn_message(turn: ModelTurn) -> AgentMessage:
        if isinstance(turn, FinalTurn):
            content = turn.content
        else:
            content = json.dumps(
                turn.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        return AgentMessage(role=MessageRole.ASSISTANT, content=content)
