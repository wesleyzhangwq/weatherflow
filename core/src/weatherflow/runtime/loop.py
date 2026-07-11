import asyncio
import json
from typing import Any

from pydantic import TypeAdapter

from weatherflow.capabilities import CapabilitySnapshotRepository, ToolSpec
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs import Run, RunCoordinator, RunRepository, RunStatus
from weatherflow.runtime.action_execution import (
    ActionExecutionCoordinator,
    ActionExecutionStatus,
)
from weatherflow.runtime.checkpoints import RunCheckpoint
from weatherflow.runtime.models import (
    AgentDefinition,
    AgentMessage,
    DelegationTurn,
    FinalTurn,
    LeafDelegationError,
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
from weatherflow.runtime.workers import WorkerCoordinator, WorkerDefinitionError
from weatherflow.storage import Database
from weatherflow.trust import (
    ActionStatus,
    ApprovalCoordinator,
    DecisionKind,
    SupervisedPolicy,
)
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
        approval_coordinator: ApprovalCoordinator | None = None,
        action_execution: ActionExecutionCoordinator | None = None,
        worker_coordinator: WorkerCoordinator | None = None,
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
        self.approval_coordinator = approval_coordinator
        self.action_execution = action_execution
        self.worker_coordinator = worker_coordinator

    async def run(
        self,
        *,
        run_id: str,
        workspace: Workspace,
        agent: AgentDefinition,
    ) -> LoopOutcome:
        initial = await self.runs.get(run_id)
        if initial is None:
            raise LookupError(run_id)
        checkpoint = await self._ensure_checkpoint(initial)
        if initial.status is RunStatus.WAITING_APPROVAL:
            return await self._waiting_outcome(initial, checkpoint)
        run = await self._ensure_running(run_id)
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
                try:
                    turn = agent.validate_turn(await self._complete_with_retry(request))
                except (TimeoutError, ConnectionError):
                    return await self._pause_for_model(run, checkpoint)
                except LeafDelegationError:
                    return await self._fail(
                        run,
                        checkpoint,
                        f"leaf Worker {agent.agent_id} attempted nested delegation",
                    )
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
                    dispatched = await self._dispatch_approval(
                        run, checkpoint, turn, tool, workspace
                    )
                    if isinstance(dispatched, LoopOutcome):
                        return dispatched
                    checkpoint = dispatched
                    continue
                checkpoint = await self._execute_safe_tool(run, checkpoint, turn, tool)
                continue
            if isinstance(turn, DelegationTurn):
                if self.worker_coordinator is None:
                    output = {"error": "delegation runtime is not installed"}
                else:
                    try:
                        result = await self.worker_coordinator.delegate(
                            parent_run_id=run.id,
                            delegation_id=f"step-{checkpoint.step_index}",
                            workspace=workspace,
                            agent_id=turn.agent_id,
                            task=turn.task,
                        )
                        output = result.model_dump(mode="json")
                    except (WorkerDefinitionError, ValueError) as error:
                        output = {"error": str(error)}
                checkpoint = await self._record_observation(
                    checkpoint,
                    turn,
                    output,
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

    async def _dispatch_approval(
        self,
        run: Run,
        checkpoint: RunCheckpoint,
        turn: ToolCallTurn,
        tool: ToolSpec,
        workspace: Workspace,
    ) -> LoopOutcome | RunCheckpoint:
        if self.approval_coordinator is None:
            raise RuntimeError("approval coordinator is not configured")
        current_run = await self.runs.get(run.id)
        if current_run is None:
            raise LookupError(run.id)
        call_key = turn.call_id or f"step-{checkpoint.step_index}-{tool.tool_id}"
        bundle = await self.approval_coordinator.propose(
            run_id=run.id,
            expected_run_version=current_run.version,
            tool=tool,
            workspace=workspace,
            arguments=turn.arguments,
            idempotency_key=f"{run.id}:{call_key}",
            preview={"tool_id": tool.tool_id, "arguments": turn.arguments},
        )
        if bundle.action.status in {ActionStatus.APPROVED, ActionStatus.EXECUTING}:
            if self.action_execution is None:
                raise RuntimeError("action execution coordinator is not configured")
            try:
                executor = self.executors.require(tool.tool_id)
            except ToolExecutorNotFound:
                return await self._record_observation(
                    checkpoint, turn, {"error": f"no executor registered for {tool.tool_id}"}
                )
            executed = await self.action_execution.execute(
                action_id=bundle.action.id,
                tool=tool,
                workspace=workspace,
                executor=executor,
            )
            if executed.status is ActionExecutionStatus.NEEDS_REVIEW:
                return LoopOutcome(
                    run_id=run.id,
                    status=LoopStatus.NEEDS_REVIEW,
                    action_id=executed.action.id,
                    error=executed.error,
                )
            output = (
                executed.result.output
                if executed.result is not None
                else {"error": executed.error or "action failed"}
            )
            return await self._record_observation(checkpoint, turn, output)
        if bundle.action.status in {
            ActionStatus.DENIED,
            ActionStatus.CANCELLED,
            ActionStatus.FAILED,
        }:
            return await self._record_observation(
                checkpoint,
                turn,
                {"error": f"action {bundle.action.status.value}"},
            )
        desired = checkpoint.model_copy(update={"pending_action_id": bundle.action.id})
        async with self.database.transaction() as connection:
            await self.checkpoints.save_in(connection, desired, expected_version=checkpoint.version)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="runtime.approval_parked",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=run.id,
                    correlation_id=run.id,
                    payload={
                        "action_id": bundle.action.id,
                        "approval_id": bundle.approval.id,
                    },
                ),
            )
        return LoopOutcome(
            run_id=run.id,
            status=LoopStatus.WAITING_APPROVAL,
            action_id=bundle.action.id,
            approval_id=bundle.approval.id,
        )

    async def _waiting_outcome(self, run: Run, checkpoint: RunCheckpoint) -> LoopOutcome:
        if self.approval_coordinator is None or checkpoint.pending_action_id is None:
            raise RuntimeError(f"run {run.id} is waiting without a pending action")
        action = await self.approval_coordinator.actions.get(checkpoint.pending_action_id)
        if action is None:
            raise RuntimeError(checkpoint.pending_action_id)
        approval = await self.approval_coordinator.approvals.get_by_action_id(action.id)
        if approval is None:
            raise RuntimeError(action.id)
        return LoopOutcome(
            run_id=run.id,
            status=LoopStatus.WAITING_APPROVAL,
            action_id=action.id,
            approval_id=approval.id,
        )

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
                "pending_action_id": None,
            }
        )
        async with self.database.transaction() as connection:
            saved = await self.checkpoints.save_in(
                connection, desired, expected_version=checkpoint.version
            )
            event_type = (
                "tool.executed" if isinstance(turn, ToolCallTurn) else "worker.result_observed"
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type=event_type,
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

    async def _complete_with_retry(self, request: ModelRequest) -> ModelTurn:
        for attempt in range(1, 4):
            try:
                return await self.model.complete(request)
            except (TimeoutError, ConnectionError):
                if attempt == 3:
                    raise
                await self.ledger.append(
                    Event.new(
                        type="runtime.model_retry",
                        actor=Actor.SYSTEM,
                        stream_kind="run",
                        stream_id=request.run_id,
                        correlation_id=request.run_id,
                        payload={"attempt": attempt, "max_attempts": 3},
                    )
                )
                await asyncio.sleep(0.05 * (2 ** (attempt - 1)))
        raise RuntimeError("unreachable")

    async def _pause_for_model(self, run: Run, checkpoint: RunCheckpoint) -> LoopOutcome:
        state = dict(checkpoint.state)
        state["pause_reason"] = "model_provider_unavailable"
        desired = checkpoint.model_copy(update={"state": state})
        current = await self.runs.get(run.id)
        if current is None:
            raise LookupError(run.id)
        async with self.database.transaction() as connection:
            await self.checkpoints.save_in(connection, desired, expected_version=checkpoint.version)
            await self.run_coordinator.transition_in(
                connection,
                run_id=run.id,
                target=RunStatus.PAUSED,
                expected_version=current.version,
                error_class="ModelProviderUnavailable",
                error_message="model provider unavailable after bounded retry",
            )
        return LoopOutcome(
            run_id=run.id,
            status=LoopStatus.PAUSED,
            error="model provider unavailable after bounded retry",
        )

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
