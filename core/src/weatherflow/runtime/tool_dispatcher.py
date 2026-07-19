import asyncio
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from weatherflow.capabilities import ToolEffect, ToolSpec
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs import Run, RunRepository
from weatherflow.runtime.action_execution import (
    ActionExecutionCoordinator,
    ActionExecutionStatus,
)
from weatherflow.runtime.checkpoints import RunCheckpoint
from weatherflow.runtime.models import (
    AgentMessage,
    MessageRole,
    ToolCallTurn,
    ToolExecutionContext,
)
from weatherflow.runtime.outcomes import BoundedObservation, LoopOutcome, LoopStatus
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
    ephemeral_observation: AgentMessage | None = None
    redaction_values: tuple[str, ...] = ()
    durable_projection: dict[str, Any] | None = None
    tool_free_next_turn: bool = False

    @model_validator(mode="after")
    def validate_next_state(self) -> Self:
        if (self.checkpoint is None) == (self.outcome is None):
            raise ValueError("tool dispatch must produce one durable next state")
        if self.outcome is not None and (
            self.ephemeral_observation is not None
            or self.redaction_values
            or self.durable_projection is not None
            or self.tool_free_next_turn
        ):
            raise ValueError("terminal tool dispatch cannot carry an ephemeral observation")
        if self.ephemeral_observation is None and (
            self.redaction_values or self.durable_projection is not None
        ):
            raise ValueError("ephemeral metadata requires an ephemeral observation")
        return self

    @classmethod
    def from_checkpoint(
        cls,
        checkpoint: RunCheckpoint,
        *,
        ephemeral_observation: AgentMessage | None = None,
        redaction_values: tuple[str, ...] = (),
        durable_projection: dict[str, Any] | None = None,
        tool_free_next_turn: bool = False,
    ) -> "ToolDispatchResult":
        return cls(
            checkpoint=checkpoint,
            ephemeral_observation=ephemeral_observation,
            redaction_values=redaction_values,
            durable_projection=durable_projection,
            tool_free_next_turn=tool_free_next_turn,
        )

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
        transient_result = None
        tool_free_next_turn = False
        try:
            executor = self.executors.require(tool.tool_id)
            result = await asyncio.wait_for(
                executor.execute(
                    tool,
                    request.turn.arguments,
                    ToolExecutionContext(
                        run_id=request.run.id,
                        workspace_id=request.run.workspace_id,
                        time_anchor=request.run.created_at,
                    ),
                ),
                timeout=tool.timeout_seconds,
            )
            output_validation = validate_tool_output(tool.output_schema, result.output)
            if output_validation.valid:
                output = result.output
                tool_free_next_turn = result.tool_free_next_turn
                if result.transient:
                    transient_result = result
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
        if transient_result is not None:
            if not _transient_observation_allowed(tool):
                return await self._observe(
                    request,
                    {
                        "error": "transient_tool_output_forbidden",
                        "message": "Only built-in ActivityWatch observe tools may be transient.",
                    },
                )
            assert transient_result.checkpoint_output is not None
            return await self._observe_transient(
                request,
                output=output,
                checkpoint_output=transient_result.checkpoint_output,
            )
        return await self._observe(
            request,
            output,
            tool_free_next_turn=tool_free_next_turn,
        )

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
        *,
        tool_free_next_turn: bool = False,
    ) -> ToolDispatchResult:
        checkpoint = await self.committer.record_observation(
            request.checkpoint,
            request.turn,
            output,
            clear_pending=request.clear_pending,
            batch_next_index=request.batch_next_index,
            tool_free_next_turn=tool_free_next_turn,
        )
        return ToolDispatchResult.from_checkpoint(
            checkpoint,
            tool_free_next_turn=tool_free_next_turn,
        )

    async def _observe_transient(
        self,
        request: ToolDispatchRequest,
        *,
        output: dict[str, Any],
        checkpoint_output: dict[str, Any],
    ) -> ToolDispatchResult:
        observation_key = (
            f"{request.checkpoint.run_id}:{request.checkpoint.step_index}:"
            f"{request.batch_next_index}:{request.turn.tool_id}"
        )
        safe_projection = _safe_transient_projection(
            checkpoint_output,
            output=output,
        )
        checkpoint = await self.committer.record_transient_observation(
            request.checkpoint,
            request.turn,
            safe_projection,
            observation_key=observation_key,
        )
        observation = BoundedObservation.from_output(output, max_chars=128 * 1024)
        message = AgentMessage(
            role=MessageRole.TOOL,
            name=request.turn.tool_id,
            tool_call_id=request.turn.call_id,
            content=json.dumps(
                observation.output,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        return ToolDispatchResult.from_checkpoint(
            checkpoint,
            ephemeral_observation=message,
            redaction_values=_transient_redaction_values(observation.output),
            durable_projection=safe_projection,
            tool_free_next_turn=True,
        )

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


_TRANSIENT_PROJECTION_FIELDS = frozenset(
    {
        "operation",
        "data_classification",
        "fact_count",
        "item_count",
        "summary_count",
        "window_fact_count",
        "web_fact_count",
        "afk_fact_count",
        "redaction_count",
        "truncated",
        "window_start",
        "window_end",
        "source_health",
        "active_seconds",
        "afk_seconds",
        "category_rule_version",
        "coverage_ratio",
        "coverage_status",
        "app_switch_count",
        "category_switch_count",
        "tab_switch_count",
        "application_switches",
        "category_switches",
        "tab_switches",
        "context_switches",
    }
)


def _transient_observation_allowed(tool: ToolSpec) -> bool:
    return (
        tool.effect is ToolEffect.OBSERVE
        and tool.source == "builtin.activitywatch"
        and tool.tool_id.startswith("activity.")
    )


def _safe_transient_projection(
    projection: dict[str, Any],
    *,
    output: dict[str, Any],
) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in _TRANSIENT_PROJECTION_FIELDS:
        value = projection.get(key)
        if value is None or isinstance(value, (bool, int, float, str)):
            safe[key] = value[:300] if isinstance(value, str) else value
    category_seconds = projection.get("category_seconds")
    if isinstance(category_seconds, Mapping):
        safe["category_seconds"] = {
            name[:300]: float(seconds)
            for name, seconds in list(category_seconds.items())[:50]
            if isinstance(name, str)
            and isinstance(seconds, (int, float))
            and math.isfinite(float(seconds))
            and seconds >= 0
        }
    episodes = projection.get("category_episodes")
    if isinstance(episodes, (list, tuple)):
        safe_episodes: list[dict[str, Any]] = []
        for episode in episodes[:24]:
            if not isinstance(episode, Mapping):
                continue
            start = episode.get("start")
            end = episode.get("end")
            category = episode.get("category")
            duration = episode.get("duration_seconds")
            if not (
                isinstance(start, str)
                and isinstance(end, str)
                and isinstance(category, str)
                and isinstance(duration, (int, float))
                and math.isfinite(float(duration))
                and duration >= 0
            ):
                continue
            safe_episodes.append(
                {
                    "start": start[:64],
                    "end": end[:64],
                    "duration_seconds": float(duration),
                    "category": category[:300],
                }
            )
        safe["category_episodes"] = safe_episodes
    transitions = projection.get("category_transitions")
    if isinstance(transitions, (list, tuple)):
        safe_transitions: list[dict[str, Any]] = []
        for transition in transitions[:24]:
            if not isinstance(transition, Mapping):
                continue
            occurred_at = transition.get("occurred_at")
            from_category = transition.get("from_category")
            to_category = transition.get("to_category")
            gap_seconds = transition.get("gap_seconds")
            if not (
                isinstance(occurred_at, str)
                and isinstance(from_category, str)
                and isinstance(to_category, str)
                and isinstance(gap_seconds, (int, float))
                and math.isfinite(float(gap_seconds))
                and gap_seconds >= 0
            ):
                continue
            safe_transitions.append(
                {
                    "occurred_at": occurred_at[:64],
                    "from_category": from_category[:300],
                    "to_category": to_category[:300],
                    "gap_seconds": float(gap_seconds),
                }
            )
        safe["category_transitions"] = safe_transitions
    summary_items = projection.get("summary_items")
    if isinstance(summary_items, (list, tuple)):
        safe_summary_items: list[dict[str, Any]] = []
        for item in summary_items[:20]:
            if not isinstance(item, Mapping):
                continue
            window_start = item.get("window_start")
            window_end = item.get("window_end")
            finality = item.get("finality")
            if not (
                isinstance(window_start, str)
                and isinstance(window_end, str)
                and isinstance(finality, str)
            ):
                continue
            safe_item: dict[str, Any] = {
                "window_start": window_start[:64],
                "window_end": window_end[:64],
                "finality": finality[:32],
            }
            for field in (
                "revision_number",
                "context_switch_count",
                "evidence_count",
            ):
                value = item.get(field)
                if isinstance(value, int) and value >= 0:
                    safe_item[field] = value
            for field in ("active_seconds", "afk_seconds"):
                value = item.get(field)
                if isinstance(value, (int, float)) and math.isfinite(float(value)) and value >= 0:
                    safe_item[field] = float(value)
            for field, maximum in (
                ("summary_id", 128),
                ("category_rule_version", 128),
            ):
                value = item.get(field)
                if isinstance(value, str):
                    safe_item[field] = value[:maximum]
            safe_summary_items.append(safe_item)
        safe["summary_items"] = safe_summary_items
    encoded = json.dumps(
        output,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    safe["observation_digest"] = hashlib.sha256(encoded).hexdigest()
    return safe


def _transient_redaction_values(output: dict[str, Any]) -> tuple[str, ...]:
    values: set[str] = set()

    sensitive_scalar_fields = frozenset(
        {
            "application",
            "app_name",
            "title",
            "window_title",
            "url",
            "domain",
            "bucket_id",
            "event_id",
            "evidence_key",
            "source_id",
            "document_name",
        }
    )

    def visit(value: Any, *, field: str | None = None) -> None:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized and (len(normalized) >= 3 or field in sensitive_scalar_fields):
                values.add(normalized)
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                visit(item, field=str(key))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item, field=field)

    visit(output)
    return tuple(sorted(values, key=lambda item: (-len(item), item.casefold())))
