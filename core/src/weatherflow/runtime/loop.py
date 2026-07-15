import json
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter

from weatherflow.capabilities import CapabilitySnapshotRepository, ToolSpec
from weatherflow.continuations import (
    ProviderContinuationRepository,
    ProviderContinuationUnavailableError,
)
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs import Run, RunCoordinator, RunRepository, RunStatus
from weatherflow.runtime.action_execution import (
    ActionExecutionCoordinator,
)
from weatherflow.runtime.agent_core import AgentCore, AgentCoreEvent, AgentCoreEventKind
from weatherflow.runtime.checkpoints import RunCheckpoint
from weatherflow.runtime.controls import RunControlCoordinator, RunControlRepository
from weatherflow.runtime.models import (
    AgentDefinition,
    AgentMessage,
    DelegationTurn,
    FinalTurn,
    LeafDelegationError,
    MessageRole,
    ModelCompletion,
    ModelRequest,
    ModelTurn,
    ToolCallBatchTurn,
    ToolCallTurn,
)
from weatherflow.runtime.outcomes import LoopOutcome, LoopStatus
from weatherflow.runtime.protocols import (
    ModelAdapter,
    ModelConfigurationRequiredError,
    ModelResolver,
    ModelRouteUnavailableError,
)
from weatherflow.runtime.repository import RunCheckpointRepository
from weatherflow.runtime.tool_dispatcher import (
    ToolDispatcher,
    ToolDispatchRequest,
)
from weatherflow.runtime.tools import ToolExecutorRegistry
from weatherflow.runtime.turn_committer import TurnCommitter
from weatherflow.runtime.workers import WorkerCoordinator, WorkerDefinitionError
from weatherflow.storage import Database
from weatherflow.trust import (
    ApprovalCoordinator,
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
        continuations: ProviderContinuationRepository | None = None,
        snapshots: CapabilitySnapshotRepository,
        ledger: EventLedger,
        model: ModelAdapter,
        model_resolver: ModelResolver | None = None,
        executors: ToolExecutorRegistry,
        policy: SupervisedPolicy,
        approval_coordinator: ApprovalCoordinator | None = None,
        action_execution: ActionExecutionCoordinator | None = None,
        worker_coordinator: WorkerCoordinator | None = None,
        agent_core: AgentCore | None = None,
        turn_committer: TurnCommitter | None = None,
        tool_dispatcher: ToolDispatcher | None = None,
        control_coordinator: RunControlCoordinator | None = None,
    ) -> None:
        self.database = database
        self.runs = runs
        self.run_coordinator = run_coordinator
        self.checkpoints = checkpoints
        self.continuations = continuations
        self.snapshots = snapshots
        self.ledger = ledger
        self.model = model
        self.model_resolver = model_resolver
        self.executors = executors
        self.policy = policy
        self.approval_coordinator = approval_coordinator
        self.action_execution = action_execution
        self.worker_coordinator = worker_coordinator
        self.control_coordinator = control_coordinator or RunControlCoordinator(
            database=database,
            runs=runs,
            controls=RunControlRepository(database),
            checkpoints=checkpoints,
            ledger=ledger,
        )
        self.agent_core = agent_core or AgentCore()
        self.turn_committer = turn_committer or TurnCommitter(
            database=database,
            checkpoints=checkpoints,
            ledger=ledger,
            continuations=continuations,
        )
        self.tool_dispatcher = tool_dispatcher or ToolDispatcher(
            database=database,
            runs=runs,
            checkpoints=checkpoints,
            ledger=ledger,
            executors=executors,
            policy=policy,
            committer=self.turn_committer,
            approval_coordinator=approval_coordinator,
            action_execution=action_execution,
        )

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
        try:
            active_model = await self._model_for_run(run_id)
        except ModelConfigurationRequiredError:
            return await self._model_configuration_required(initial, checkpoint)
        except ModelRouteUnavailableError:
            return await self._model_route_needs_review(initial, checkpoint)
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
            budget_error = self._budget_error(run, checkpoint)
            if budget_error is not None:
                return await self._fail(run, checkpoint, budget_error)
            pending = checkpoint.state.get("pending_turn")
            if pending is None:
                checkpoint = await self.control_coordinator.apply_before_model(checkpoint)
                if checkpoint.step_index >= step_limit:
                    return await self._fail(run, checkpoint, "step budget exhausted")
                try:
                    provider_continuations = await self._continuations_for(
                        checkpoint,
                        active_model,
                    )
                    request = ModelRequest(
                        run_id=run_id,
                        agent=agent,
                        messages=checkpoint.transcript,
                        tools=tools,
                        provider_continuations=provider_continuations,
                    )
                    completion = await self.agent_core.next_turn(
                        request,
                        active_model,
                        emit=self._record_agent_core_event,
                    )
                    turn = completion.turn
                except (TimeoutError, ConnectionError):
                    return await self._pause_for_model(run, checkpoint)
                except ProviderContinuationUnavailableError as error:
                    return await self._needs_review(run, checkpoint, str(error))
                except LeafDelegationError:
                    return await self._fail(
                        run,
                        checkpoint,
                        f"leaf Worker {agent.agent_id} attempted nested delegation",
                    )
                try:
                    checkpoint = await self._record_turn(
                        checkpoint,
                        completion.model_copy(update={"turn": turn}),
                        active_model,
                    )
                    budget_error = self._budget_error(run, checkpoint)
                    if budget_error is not None:
                        return await self._fail(run, checkpoint, budget_error)
                except ProviderContinuationUnavailableError as error:
                    return await self._needs_review(run, checkpoint, str(error))
            else:
                turn = TypeAdapter(ModelTurn).validate_python(pending)

            if isinstance(turn, FinalTurn):
                committed = await self._commit_final(run, checkpoint, turn.content)
                if isinstance(committed, RunCheckpoint):
                    checkpoint = committed
                    continue
                return committed
            if isinstance(turn, ToolCallTurn | ToolCallBatchTurn):
                calls = turn.calls if isinstance(turn, ToolCallBatchTurn) else (turn,)
                start_index = (
                    int(checkpoint.state.get("batch_next_index", 0))
                    if isinstance(turn, ToolCallBatchTurn)
                    else 0
                )
                for index in range(start_index, len(calls)):
                    call = calls[index]
                    clear_pending = index == len(calls) - 1
                    dispatched = await self._dispatch_tool_call(
                        run=run,
                        checkpoint=checkpoint,
                        turn=call,
                        tool_map=tool_map,
                        workspace=workspace,
                        clear_pending=clear_pending,
                        batch_next_index=index + 1,
                    )
                    if isinstance(dispatched, LoopOutcome):
                        return dispatched
                    checkpoint = dispatched
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

    async def _record_turn(
        self,
        checkpoint: RunCheckpoint,
        completion: ModelCompletion,
        active_model: ModelAdapter,
    ) -> RunCheckpoint:
        return await self.turn_committer.record_turn(
            checkpoint,
            completion,
            active_model,
        )

    @staticmethod
    def _budget_error(run: Run, checkpoint: RunCheckpoint) -> str | None:
        elapsed = (datetime.now(UTC) - run.created_at).total_seconds()
        if elapsed >= run.budget.timeout_seconds:
            return "run timeout budget exhausted"
        if run.budget.max_cost_usd is None:
            return None
        usage = checkpoint.state.get("runtime_usage", {})
        cost = usage.get("cost_usd")
        if checkpoint.step_index > 0 and (usage.get("cost_status") != "known" or cost is None):
            return "run cost budget cannot be enforced: model cost is unknown"
        if cost is not None and float(cost) > run.budget.max_cost_usd:
            return "run cost budget exhausted"
        return None

    async def _dispatch_tool_call(
        self,
        *,
        run: Run,
        checkpoint: RunCheckpoint,
        turn: ToolCallTurn,
        tool_map: dict[str, ToolSpec],
        workspace: Workspace,
        clear_pending: bool,
        batch_next_index: int,
    ) -> LoopOutcome | RunCheckpoint:
        result = await self.tool_dispatcher.dispatch(
            ToolDispatchRequest(
                run=run,
                checkpoint=checkpoint,
                turn=turn,
                workspace=workspace,
                clear_pending=clear_pending,
                batch_next_index=batch_next_index,
            ),
            tool_map,
        )
        if result.outcome is not None:
            return result.outcome
        if result.checkpoint is None:
            raise RuntimeError("tool dispatch returned no durable next state")
        return result.checkpoint

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
        *,
        clear_pending: bool = True,
        batch_next_index: int = 1,
    ) -> RunCheckpoint:
        return await self.turn_committer.record_observation(
            checkpoint,
            turn,
            output,
            clear_pending=clear_pending,
            batch_next_index=batch_next_index,
        )

    async def _commit_final(
        self,
        run: Run,
        checkpoint: RunCheckpoint,
        content: str,
    ) -> LoopOutcome | RunCheckpoint:
        state = dict(checkpoint.state)
        state.pop("pending_turn", None)
        state["result_committed"] = True
        desired = checkpoint.model_copy(update={"state": state})
        async with self.database.transaction() as connection:
            controlled = await self.control_coordinator.apply_at_final_boundary_in(
                connection,
                checkpoint,
            )
            if controlled is not None:
                return controlled
            current_run = await self.runs.get_in(connection, run.id)
            if current_run is None:
                raise LookupError(run.id)
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
            if self.continuations is not None:
                await self.continuations.delete_run_in(connection, run.id)
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
            if self.continuations is not None:
                await self.continuations.delete_run_in(connection, run.id)
        return LoopOutcome(run_id=run.id, status=LoopStatus.FAILED, error=error)

    async def _record_agent_core_event(self, event: AgentCoreEvent) -> None:
        event_types = {
            AgentCoreEventKind.MODEL_START: "runtime.model_started",
            AgentCoreEventKind.MODEL_RETRY: "runtime.model_retry",
            AgentCoreEventKind.MODEL_END: "runtime.model_completed",
            AgentCoreEventKind.MODEL_ERROR: "runtime.model_failed",
        }
        await self.ledger.append(
            Event.new(
                type=event_types[event.kind],
                actor=Actor.SYSTEM,
                stream_kind="run",
                stream_id=event.run_id,
                correlation_id=event.run_id,
                payload={
                    "attempt": event.attempt,
                    "max_attempts": event.max_attempts,
                    "turn_kind": event.turn_kind,
                },
            )
        )

    async def _continuations_for(
        self,
        checkpoint: RunCheckpoint,
        active_model: ModelAdapter,
    ):
        provider = getattr(active_model, "continuation_provider", None)
        model = getattr(active_model, "continuation_model", None)
        if provider is None or model is None:
            return ()
        if self.continuations is None:
            raise ProviderContinuationUnavailableError("provider continuation store is unavailable")
        required_steps = tuple(
            index
            for index, message in enumerate(
                (item for item in checkpoint.transcript if item.role is MessageRole.ASSISTANT),
                start=1,
            )
            if self._assistant_requires_continuation(message)
        )
        return await self.continuations.require_for_run(
            checkpoint.run_id,
            provider=provider,
            model=model,
            required_steps=required_steps,
        )

    async def _model_for_run(self, run_id: str) -> ModelAdapter:
        if self.model_resolver is None:
            return self.model
        resolved = await self.model_resolver.resolve(run_id)
        return resolved or self.model

    @staticmethod
    def _assistant_requires_continuation(message: AgentMessage) -> bool:
        try:
            value = json.loads(message.content)
        except ValueError:
            return False
        return isinstance(value, dict) and value.get("kind") in {
            "tool_call",
            "tool_call_batch",
            "delegation",
        }

    async def _needs_review(
        self,
        run: Run,
        checkpoint: RunCheckpoint,
        reason: str,
    ) -> LoopOutcome:
        state = dict(checkpoint.state)
        state["review_reason"] = "provider_continuation_unavailable"
        desired = checkpoint.model_copy(update={"state": state})
        current = await self.runs.get(run.id)
        if current is None:
            raise LookupError(run.id)
        async with self.database.transaction() as connection:
            await self.checkpoints.save_in(connection, desired, expected_version=checkpoint.version)
            await self.run_coordinator.transition_in(
                connection,
                run_id=run.id,
                target=RunStatus.NEEDS_REVIEW,
                expected_version=current.version,
                error_class="ProviderContinuationUnavailable",
                error_message="provider continuation unavailable; explicit review required",
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="runtime.provider_continuation_unavailable",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=run.id,
                    correlation_id=run.id,
                    payload={"reason": reason[:200]},
                ),
            )
        return LoopOutcome(
            run_id=run.id,
            status=LoopStatus.NEEDS_REVIEW,
            error="provider continuation unavailable; explicit review required",
        )

    async def _model_route_needs_review(
        self,
        run: Run,
        checkpoint: RunCheckpoint,
    ) -> LoopOutcome:
        state = dict(checkpoint.state)
        state["review_reason"] = "model_route_unavailable"
        desired = checkpoint.model_copy(update={"state": state})
        current = await self.runs.get(run.id)
        if current is None:
            raise LookupError(run.id)
        async with self.database.transaction() as connection:
            await self.checkpoints.save_in(
                connection,
                desired,
                expected_version=checkpoint.version,
            )
            await self.run_coordinator.transition_in(
                connection,
                run_id=run.id,
                target=RunStatus.NEEDS_REVIEW,
                expected_version=current.version,
                error_class="ModelRouteUnavailable",
                error_message="frozen model route unavailable; explicit review required",
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="runtime.model_route_unavailable",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=run.id,
                    correlation_id=run.id,
                    payload={},
                ),
            )
        return LoopOutcome(
            run_id=run.id,
            status=LoopStatus.NEEDS_REVIEW,
            error="frozen model route unavailable; explicit review required",
        )

    async def _model_configuration_required(
        self,
        run: Run,
        checkpoint: RunCheckpoint,
    ) -> LoopOutcome:
        current = await self.runs.get(run.id)
        if current is None:
            raise LookupError(run.id)
        if current.status is RunStatus.QUEUED:
            current = await self.run_coordinator.transition(
                run_id=current.id,
                target=RunStatus.PLANNING,
                expected_version=current.version,
            )
        if current.status in {RunStatus.PLANNING, RunStatus.RUNNING}:
            state = dict(checkpoint.state)
            state["waiting_for"] = "model_configuration"
            desired = checkpoint.model_copy(update={"state": state})
            async with self.database.transaction() as connection:
                await self.checkpoints.save_in(
                    connection, desired, expected_version=checkpoint.version
                )
                current = await self.run_coordinator.transition_in(
                    connection,
                    run_id=run.id,
                    target=RunStatus.WAITING_USER,
                    expected_version=current.version,
                    error_class="ModelConfigurationRequired",
                    error_message="configure a language model before running this task",
                )
                await self.ledger.append_in(
                    connection,
                    Event.new(
                        type="runtime.model_configuration_required",
                        actor=Actor.SYSTEM,
                        stream_kind="run",
                        stream_id=run.id,
                        correlation_id=run.id,
                        payload={"status": current.status.value},
                    ),
                )
        return LoopOutcome(
            run_id=run.id,
            status=LoopStatus.WAITING_USER,
            error="configure a language model before running this task",
        )

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
