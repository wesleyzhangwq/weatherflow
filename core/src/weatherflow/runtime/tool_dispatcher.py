import asyncio
import hashlib
import json
from collections.abc import Mapping
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from weatherflow.capabilities import ToolSpec
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs import Run, RunRepository
from weatherflow.runtime.action_execution import (
    ActionExecutionCoordinator,
    ActionExecutionStatus,
)
from weatherflow.runtime.checkpoints import RunCheckpoint
from weatherflow.runtime.models import ToolCallTurn, ToolExecutionContext
from weatherflow.runtime.outcomes import LoopOutcome, LoopStatus
from weatherflow.runtime.protocols import PublicToolError
from weatherflow.runtime.repository import RunCheckpointRepository
from weatherflow.runtime.tools import ToolExecutorNotFound, ToolExecutorRegistry
from weatherflow.runtime.turn_committer import TurnCommitter
from weatherflow.runtime.validation import validate_tool_arguments, validate_tool_output
from weatherflow.storage import Database
from weatherflow.trust import (
    ActionStatus,
    ApprovalCoordinator,
    DecisionKind,
    SupervisedPolicy,
)
from weatherflow.workspaces import Workspace


class ToolDispatchRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run: Run
    checkpoint: RunCheckpoint
    turn: ToolCallTurn
    workspace: Workspace
    clear_pending: bool = True
    batch_next_index: int = Field(default=1, ge=1)


class ToolDispatchResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint: RunCheckpoint | None = None
    outcome: LoopOutcome | None = None

    @model_validator(mode="after")
    def validate_next_state(self) -> Self:
        if (self.checkpoint is None) == (self.outcome is None):
            raise ValueError("tool dispatch must produce one durable next state")
        return self

    @classmethod
    def from_checkpoint(cls, checkpoint: RunCheckpoint) -> "ToolDispatchResult":
        return cls(checkpoint=checkpoint)

    @classmethod
    def from_outcome(cls, outcome: LoopOutcome) -> "ToolDispatchResult":
        return cls(outcome=outcome)


class ToolDispatcher:
    """Validate, authorize, execute, and durably observe one ordered tool call."""

    def __init__(
        self,
        *,
        database: Database,
        runs: RunRepository,
        checkpoints: RunCheckpointRepository,
        ledger: EventLedger,
        executors: ToolExecutorRegistry,
        policy: SupervisedPolicy,
        committer: TurnCommitter,
        approval_coordinator: ApprovalCoordinator | None = None,
        action_execution: ActionExecutionCoordinator | None = None,
    ) -> None:
        self.database = database
        self.runs = runs
        self.checkpoints = checkpoints
        self.ledger = ledger
        self.executors = executors
        self.policy = policy
        self.committer = committer
        self.approval_coordinator = approval_coordinator
        self.action_execution = action_execution

    async def dispatch(
        self,
        request: ToolDispatchRequest,
        tool_map: Mapping[str, ToolSpec],
    ) -> ToolDispatchResult:
        tool = tool_map.get(request.turn.tool_id)
        if tool is None:
            return await self._observe(
                request,
                {"error": f"{request.turn.tool_id} is not in frozen capability snapshot"},
            )
        validation = validate_tool_arguments(tool.input_schema, request.turn.arguments)
        if not validation.valid:
            missing_arguments = sorted(
                set(tool.input_schema.get("required", ())) - set(request.turn.arguments)
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
            return await self._observe(
                request,
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
            )
        decision = self.policy.evaluate(tool, request.workspace)
        if decision.kind in {DecisionKind.DENY, DecisionKind.HIDE}:
            return await self._observe(
                request,
                {"error": decision.reason, "decision": decision.kind.value},
            )
        if decision.kind is DecisionKind.APPROVE:
            return await self._dispatch_approval(request, tool)
        if decision.kind is DecisionKind.SANDBOX:
            return await self._dispatch_sandboxed_action(request, tool)
        return await self._execute_safe_tool(request, tool)

    async def _dispatch_sandboxed_action(
        self,
        request: ToolDispatchRequest,
        tool: ToolSpec,
    ) -> ToolDispatchResult:
        if self.approval_coordinator is None or self.action_execution is None:
            raise RuntimeError("durable action execution is not configured")
        try:
            executor = self.executors.require(tool.tool_id)
        except ToolExecutorNotFound:
            return await self._observe(
                request,
                {"error": f"no executor registered for {tool.tool_id}"},
            )
        action = await self.approval_coordinator.authorize_sandboxed(
            run_id=request.run.id,
            tool=tool,
            workspace=request.workspace,
            arguments=request.turn.arguments,
            idempotency_key=self._action_idempotency_key(request),
            preview={"tool_id": tool.tool_id, "arguments": request.turn.arguments},
        )
        if action.status is ActionStatus.SUCCEEDED:
            recovered = await self.action_execution.recover_succeeded(
                action_id=action.id,
                tool=tool,
                workspace=request.workspace,
            )
            if recovered.status is ActionExecutionStatus.NEEDS_REVIEW:
                return self._needs_review(
                    request,
                    action_id=recovered.action.id,
                    error=recovered.error,
                )
            if recovered.result is None:
                raise RuntimeError("validated succeeded action has no result")
            return await self._observe(request, recovered.result.output)
        if action.status is ActionStatus.NEEDS_REVIEW:
            return self._needs_review(
                request,
                action_id=action.id,
                error=action.error_message or "sandboxed side effect needs review",
            )
        if action.status in {
            ActionStatus.DENIED,
            ActionStatus.CANCELLED,
            ActionStatus.FAILED,
        }:
            return await self._observe(
                request,
                {"error": action.error_message or f"action {action.status.value}"},
            )
        if action.status not in {ActionStatus.APPROVED, ActionStatus.EXECUTING}:
            raise RuntimeError(f"sandboxed action is {action.status.value}")
        executed = await self.action_execution.execute(
            action_id=action.id,
            tool=tool,
            workspace=request.workspace,
            executor=executor,
        )
        if executed.status is ActionExecutionStatus.NEEDS_REVIEW:
            return self._needs_review(
                request,
                action_id=executed.action.id,
                error=executed.error,
            )
        output = (
            executed.result.output
            if executed.result is not None
            else {"error": executed.error or "action failed"}
        )
        return await self._observe(request, output)

    async def _execute_safe_tool(
        self,
        request: ToolDispatchRequest,
        tool: ToolSpec,
    ) -> ToolDispatchResult:
        try:
            executor = self.executors.require(tool.tool_id)
            result = await asyncio.wait_for(
                executor.execute(
                    tool,
                    request.turn.arguments,
                    ToolExecutionContext(
                        run_id=request.run.id,
                        workspace_id=request.run.workspace_id,
                    ),
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
        return await self._observe(request, output)

    async def _dispatch_approval(
        self,
        request: ToolDispatchRequest,
        tool: ToolSpec,
    ) -> ToolDispatchResult:
        if self.approval_coordinator is None:
            raise RuntimeError("approval coordinator is not configured")
        current_run = await self.runs.get(request.run.id)
        if current_run is None:
            raise LookupError(request.run.id)
        bundle = await self.approval_coordinator.propose(
            run_id=request.run.id,
            expected_run_version=current_run.version,
            tool=tool,
            workspace=request.workspace,
            arguments=request.turn.arguments,
            idempotency_key=self._action_idempotency_key(request),
            preview={"tool_id": tool.tool_id, "arguments": request.turn.arguments},
        )
        if bundle.action.status is ActionStatus.SUCCEEDED:
            if self.action_execution is None:
                raise RuntimeError("action execution coordinator is not configured")
            recovered = await self.action_execution.recover_succeeded(
                action_id=bundle.action.id,
                tool=tool,
                workspace=request.workspace,
            )
            if recovered.status is ActionExecutionStatus.NEEDS_REVIEW:
                return self._needs_review(
                    request,
                    action_id=recovered.action.id,
                    error=recovered.error,
                )
            if recovered.result is None:
                raise RuntimeError("validated succeeded action has no result")
            return await self._observe(request, recovered.result.output)
        if bundle.action.status in {ActionStatus.APPROVED, ActionStatus.EXECUTING}:
            if self.action_execution is None:
                raise RuntimeError("action execution coordinator is not configured")
            try:
                executor = self.executors.require(tool.tool_id)
            except ToolExecutorNotFound:
                return await self._observe(
                    request,
                    {"error": f"no executor registered for {tool.tool_id}"},
                )
            executed = await self.action_execution.execute(
                action_id=bundle.action.id,
                tool=tool,
                workspace=request.workspace,
                executor=executor,
            )
            if executed.status is ActionExecutionStatus.NEEDS_REVIEW:
                return self._needs_review(
                    request,
                    action_id=executed.action.id,
                    error=executed.error,
                )
            output = (
                executed.result.output
                if executed.result is not None
                else {"error": executed.error or "action failed"}
            )
            return await self._observe(request, output)
        if bundle.action.status in {
            ActionStatus.DENIED,
            ActionStatus.CANCELLED,
            ActionStatus.FAILED,
        }:
            return await self._observe(
                request,
                {"error": f"action {bundle.action.status.value}"},
            )
        parked_state = dict(request.checkpoint.state)
        parked_state["batch_next_index"] = request.batch_next_index - 1
        desired = request.checkpoint.model_copy(
            update={"pending_action_id": bundle.action.id, "state": parked_state}
        )
        async with self.database.transaction() as connection:
            await self.checkpoints.save_in(
                connection,
                desired,
                expected_version=request.checkpoint.version,
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="runtime.approval_parked",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=request.run.id,
                    correlation_id=request.run.id,
                    payload={
                        "action_id": bundle.action.id,
                        "approval_id": bundle.approval.id,
                    },
                ),
            )
        return ToolDispatchResult.from_outcome(
            LoopOutcome(
                run_id=request.run.id,
                status=LoopStatus.WAITING_APPROVAL,
                action_id=bundle.action.id,
                approval_id=bundle.approval.id,
            )
        )

    async def _observe(
        self,
        request: ToolDispatchRequest,
        output: dict[str, Any],
    ) -> ToolDispatchResult:
        checkpoint = await self.committer.record_observation(
            request.checkpoint,
            request.turn,
            output,
            clear_pending=request.clear_pending,
            batch_next_index=request.batch_next_index,
        )
        return ToolDispatchResult.from_checkpoint(checkpoint)

    @staticmethod
    def _needs_review(
        request: ToolDispatchRequest,
        *,
        action_id: str,
        error: str | None,
    ) -> ToolDispatchResult:
        return ToolDispatchResult.from_outcome(
            LoopOutcome(
                run_id=request.run.id,
                status=LoopStatus.NEEDS_REVIEW,
                action_id=action_id,
                error=error,
            )
        )

    @staticmethod
    def _action_idempotency_key(request: ToolDispatchRequest) -> str:
        identity = json.dumps(
            {
                "call_id": request.turn.call_id,
                "tool_id": request.turn.tool_id,
                "arguments": request.turn.arguments,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        digest = hashlib.sha256(identity).hexdigest()[:24]
        return (
            f"runtime:{request.run.id}:step:{request.checkpoint.step_index}:"
            f"slot:{request.batch_next_index - 1}:{digest}"
        )
