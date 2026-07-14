import asyncio
import hashlib
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
    ModelCompletion,
    ModelRequest,
    ModelTurn,
    ToolCallBatchTurn,
    ToolCallTurn,
    ToolExecutionContext,
)
from weatherflow.runtime.outcomes import BoundedObservation, LoopOutcome, LoopStatus
from weatherflow.runtime.protocols import (
    ModelAdapter,
    ModelConfigurationRequiredError,
    ModelResolver,
    ModelRouteUnavailableError,
    PublicToolError,
)
from weatherflow.runtime.repository import RunCheckpointRepository
from weatherflow.runtime.tools import ToolExecutorNotFound, ToolExecutorRegistry
from weatherflow.runtime.validation import validate_tool_arguments, validate_tool_output
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
                    completion = await self._complete_with_retry(request, active_model)
                    turn = agent.validate_turn(completion.turn)
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
                return await self._commit_final(run, checkpoint, turn.content)
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
        turn = completion.turn
        message = self._turn_message(turn)
        state = dict(checkpoint.state)
        state["pending_turn"] = turn.model_dump(mode="json")
        prior_usage = state.get("runtime_usage", {})
        input_tokens = int(prior_usage.get("input_tokens", 0)) + turn.usage.input_tokens
        output_tokens = int(prior_usage.get("output_tokens", 0)) + turn.usage.output_tokens
        prior_cost = prior_usage.get("cost_usd")
        prior_cost_status = prior_usage.get("cost_status")
        turn_cost_status = "known" if turn.usage.cost_usd is not None else "unknown"
        cost_status = "unknown" if "unknown" in {prior_cost_status, turn_cost_status} else "known"
        cost = (
            (float(prior_cost) if prior_cost is not None else 0.0) + turn.usage.cost_usd
            if turn.usage.cost_usd is not None
            else prior_cost
        )
        if input_tokens or output_tokens or cost is not None:
            state["runtime_usage"] = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
                "cost_status": cost_status,
            }
            pricing_version = getattr(active_model, "pricing_catalog_version", None)
            if pricing_version is not None and cost_status == "known":
                state["runtime_usage"]["pricing_catalog_version"] = pricing_version
        desired = checkpoint.model_copy(
            update={
                "step_index": checkpoint.step_index + 1,
                "transcript": (*checkpoint.transcript, message),
                "state": state,
            }
        )
        async with self.database.transaction() as connection:
            if completion.continuation is not None:
                if self.continuations is None:
                    raise ProviderContinuationUnavailableError(
                        "provider continuation store is unavailable"
                    )
                if isinstance(turn, FinalTurn):
                    raise ProviderContinuationUnavailableError(
                        "terminal model turn cannot carry a provider continuation"
                    )
                expected_provider = getattr(active_model, "continuation_provider", None)
                expected_model = getattr(active_model, "continuation_model", None)
                if (
                    completion.continuation.provider != expected_provider
                    or completion.continuation.model != expected_model
                ):
                    raise ProviderContinuationUnavailableError(
                        "provider continuation does not match the active model"
                    )
                await self.continuations.save_in(
                    connection,
                    run_id=checkpoint.run_id,
                    step_index=checkpoint.step_index + 1,
                    provider=completion.continuation.provider,
                    model=completion.continuation.model,
                    payload=completion.continuation.payload,
                )
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
                    payload={
                        "kind": turn.kind,
                        "step_index": saved.step_index,
                        "usage": turn.usage.model_dump(mode="json"),
                    },
                ),
            )
        return saved

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
        tool = tool_map.get(turn.tool_id)
        if tool is None:
            return await self._record_observation(
                checkpoint,
                turn,
                {"error": f"{turn.tool_id} is not in frozen capability snapshot"},
                clear_pending=clear_pending,
                batch_next_index=batch_next_index,
            )
        validation = validate_tool_arguments(tool.input_schema, turn.arguments)
        if not validation.valid:
            missing_arguments = sorted(
                set(tool.input_schema.get("required", ())) - set(turn.arguments)
            )
            if missing_arguments:
                message = (
                    "Retry the tool call with all required JSON fields. "
                    f"Missing: {', '.join(missing_arguments)}"
                )
            elif validation.schema_valid:
                message = "Retry the tool call with arguments matching the JSON schema."
            else:
                message = "The frozen tool schema is invalid; do not retry this tool."
            return await self._record_observation(
                checkpoint,
                turn,
                {
                    "error": (
                        "invalid_tool_arguments"
                        if validation.schema_valid
                        else "invalid_tool_schema"
                    ),
                    "message": message,
                    "details": list(validation.errors),
                    "required": tool.input_schema.get("required", []),
                    "schema": tool.input_schema,
                },
                clear_pending=clear_pending,
                batch_next_index=batch_next_index,
            )
        decision = self.policy.evaluate(tool, workspace)
        if decision.kind in {DecisionKind.DENY, DecisionKind.HIDE}:
            return await self._record_observation(
                checkpoint,
                turn,
                {"error": decision.reason, "decision": decision.kind.value},
                clear_pending=clear_pending,
                batch_next_index=batch_next_index,
            )
        if decision.kind is DecisionKind.APPROVE:
            return await self._dispatch_approval(
                run,
                checkpoint,
                turn,
                tool,
                workspace,
                clear_pending=clear_pending,
                batch_next_index=batch_next_index,
            )
        if decision.kind is DecisionKind.SANDBOX:
            return await self._dispatch_sandboxed_action(
                run,
                checkpoint,
                turn,
                tool,
                workspace,
                clear_pending=clear_pending,
                batch_next_index=batch_next_index,
            )
        return await self._execute_safe_tool(
            run,
            checkpoint,
            turn,
            tool,
            clear_pending=clear_pending,
            batch_next_index=batch_next_index,
        )

    async def _dispatch_sandboxed_action(
        self,
        run: Run,
        checkpoint: RunCheckpoint,
        turn: ToolCallTurn,
        tool: ToolSpec,
        workspace: Workspace,
        *,
        clear_pending: bool,
        batch_next_index: int,
    ) -> LoopOutcome | RunCheckpoint:
        if self.approval_coordinator is None or self.action_execution is None:
            raise RuntimeError("durable action execution is not configured")
        try:
            executor = self.executors.require(tool.tool_id)
        except ToolExecutorNotFound:
            return await self._record_observation(
                checkpoint,
                turn,
                {"error": f"no executor registered for {tool.tool_id}"},
                clear_pending=clear_pending,
                batch_next_index=batch_next_index,
            )
        action = await self.approval_coordinator.authorize_sandboxed(
            run_id=run.id,
            tool=tool,
            workspace=workspace,
            arguments=turn.arguments,
            idempotency_key=self._action_idempotency_key(
                run=run,
                checkpoint=checkpoint,
                turn=turn,
                batch_next_index=batch_next_index,
            ),
            preview={"tool_id": tool.tool_id, "arguments": turn.arguments},
        )
        if action.status is ActionStatus.SUCCEEDED:
            recovered = await self.action_execution.recover_succeeded(
                action_id=action.id,
                tool=tool,
                workspace=workspace,
            )
            if recovered.status is ActionExecutionStatus.NEEDS_REVIEW:
                return LoopOutcome(
                    run_id=run.id,
                    status=LoopStatus.NEEDS_REVIEW,
                    action_id=recovered.action.id,
                    error=recovered.error,
                )
            if recovered.result is None:
                raise RuntimeError("validated succeeded action has no result")
            return await self._record_observation(
                checkpoint,
                turn,
                recovered.result.output,
                clear_pending=clear_pending,
                batch_next_index=batch_next_index,
            )
        if action.status is ActionStatus.NEEDS_REVIEW:
            return LoopOutcome(
                run_id=run.id,
                status=LoopStatus.NEEDS_REVIEW,
                action_id=action.id,
                error=action.error_message or "sandboxed side effect needs review",
            )
        if action.status in {
            ActionStatus.DENIED,
            ActionStatus.CANCELLED,
            ActionStatus.FAILED,
        }:
            return await self._record_observation(
                checkpoint,
                turn,
                {"error": action.error_message or f"action {action.status.value}"},
                clear_pending=clear_pending,
                batch_next_index=batch_next_index,
            )
        if action.status not in {ActionStatus.APPROVED, ActionStatus.EXECUTING}:
            raise RuntimeError(f"sandboxed action is {action.status.value}")
        executed = await self.action_execution.execute(
            action_id=action.id,
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
        return await self._record_observation(
            checkpoint,
            turn,
            output,
            clear_pending=clear_pending,
            batch_next_index=batch_next_index,
        )

    async def _execute_safe_tool(
        self,
        run: Run,
        checkpoint: RunCheckpoint,
        turn: ToolCallTurn,
        tool: ToolSpec,
        *,
        clear_pending: bool = True,
        batch_next_index: int = 1,
    ) -> RunCheckpoint:
        try:
            executor = self.executors.require(tool.tool_id)
            result = await asyncio.wait_for(
                executor.execute(
                    tool,
                    turn.arguments,
                    ToolExecutionContext(run_id=run.id, workspace_id=run.workspace_id),
                ),
                timeout=tool.timeout_seconds,
            )
            output_validation = validate_tool_output(tool.output_schema, result.output)
            if output_validation.valid:
                output = result.output
            else:
                output = {
                    "error": (
                        "invalid_tool_output"
                        if output_validation.schema_valid
                        else "invalid_tool_output_schema"
                    ),
                    "message": (
                        "Tool output did not match the frozen output schema."
                        if output_validation.schema_valid
                        else "The frozen tool output schema is invalid."
                    ),
                    "details": list(output_validation.errors),
                }
        except ToolExecutorNotFound:
            output = {"error": f"no executor registered for {tool.tool_id}"}
        except TimeoutError:
            output = {
                "error": "tool_timeout",
                "message": f"{tool.tool_id} timed out after {tool.timeout_seconds}s",
            }
        except PublicToolError as error:
            output = {"error": error.code, "message": str(error)}
        except Exception:
            output = {
                "error": "tool_execution_failed",
                "message": "tool execution failed",
            }
        return await self._record_observation(
            checkpoint,
            turn,
            output,
            clear_pending=clear_pending,
            batch_next_index=batch_next_index,
        )

    async def _dispatch_approval(
        self,
        run: Run,
        checkpoint: RunCheckpoint,
        turn: ToolCallTurn,
        tool: ToolSpec,
        workspace: Workspace,
        *,
        clear_pending: bool = True,
        batch_next_index: int = 1,
    ) -> LoopOutcome | RunCheckpoint:
        if self.approval_coordinator is None:
            raise RuntimeError("approval coordinator is not configured")
        current_run = await self.runs.get(run.id)
        if current_run is None:
            raise LookupError(run.id)
        idempotency_key = self._action_idempotency_key(
            run=run,
            checkpoint=checkpoint,
            turn=turn,
            batch_next_index=batch_next_index,
        )
        bundle = await self.approval_coordinator.propose(
            run_id=run.id,
            expected_run_version=current_run.version,
            tool=tool,
            workspace=workspace,
            arguments=turn.arguments,
            idempotency_key=idempotency_key,
            preview={"tool_id": tool.tool_id, "arguments": turn.arguments},
        )
        if bundle.action.status is ActionStatus.SUCCEEDED:
            if self.action_execution is None:
                raise RuntimeError("action execution coordinator is not configured")
            recovered = await self.action_execution.recover_succeeded(
                action_id=bundle.action.id,
                tool=tool,
                workspace=workspace,
            )
            if recovered.status is ActionExecutionStatus.NEEDS_REVIEW:
                return LoopOutcome(
                    run_id=run.id,
                    status=LoopStatus.NEEDS_REVIEW,
                    action_id=recovered.action.id,
                    error=recovered.error,
                )
            if recovered.result is None:
                raise RuntimeError("validated succeeded action has no result")
            return await self._record_observation(
                checkpoint,
                turn,
                recovered.result.output,
                clear_pending=clear_pending,
                batch_next_index=batch_next_index,
            )
        if bundle.action.status in {ActionStatus.APPROVED, ActionStatus.EXECUTING}:
            if self.action_execution is None:
                raise RuntimeError("action execution coordinator is not configured")
            try:
                executor = self.executors.require(tool.tool_id)
            except ToolExecutorNotFound:
                return await self._record_observation(
                    checkpoint,
                    turn,
                    {"error": f"no executor registered for {tool.tool_id}"},
                    clear_pending=clear_pending,
                    batch_next_index=batch_next_index,
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
            return await self._record_observation(
                checkpoint,
                turn,
                output,
                clear_pending=clear_pending,
                batch_next_index=batch_next_index,
            )
        if bundle.action.status in {
            ActionStatus.DENIED,
            ActionStatus.CANCELLED,
            ActionStatus.FAILED,
        }:
            return await self._record_observation(
                checkpoint,
                turn,
                {"error": f"action {bundle.action.status.value}"},
                clear_pending=clear_pending,
                batch_next_index=batch_next_index,
            )
        parked_state = dict(checkpoint.state)
        parked_state["batch_next_index"] = batch_next_index - 1
        desired = checkpoint.model_copy(
            update={"pending_action_id": bundle.action.id, "state": parked_state}
        )
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

    @staticmethod
    def _action_idempotency_key(
        *,
        run: Run,
        checkpoint: RunCheckpoint,
        turn: ToolCallTurn,
        batch_next_index: int,
    ) -> str:
        identity = json.dumps(
            {
                "call_id": turn.call_id,
                "tool_id": turn.tool_id,
                "arguments": turn.arguments,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        digest = hashlib.sha256(identity).hexdigest()[:24]
        return f"runtime:{run.id}:step:{checkpoint.step_index}:slot:{batch_next_index - 1}:{digest}"

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
        observation = BoundedObservation.from_output(output)
        state = dict(checkpoint.state)
        if clear_pending:
            state.pop("pending_turn", None)
            state.pop("batch_next_index", None)
        else:
            state["batch_next_index"] = batch_next_index
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

    async def _complete_with_retry(
        self,
        request: ModelRequest,
        active_model: ModelAdapter,
    ) -> ModelCompletion:
        for attempt in range(1, 4):
            try:
                result = await active_model.complete(request)
                return (
                    result if isinstance(result, ModelCompletion) else ModelCompletion(turn=result)
                )
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
