from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from weatherflow.capabilities.models import ToolSpec
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs import RunCoordinator, RunRepository, RunStatus
from weatherflow.runtime.models import ToolExecutionContext, ToolExecutionResult
from weatherflow.runtime.protocols import ToolExecutor
from weatherflow.storage import Database
from weatherflow.trust import (
    Action,
    ActionNotFoundError,
    ActionRepository,
    ActionStatus,
    ApprovalPolicyError,
    DecisionKind,
    SupervisedPolicy,
)
from weatherflow.workspaces import Workspace


class DefinitiveToolError(RuntimeError):
    pass


class ActionExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class ActionExecutionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ActionExecutionStatus
    action: Action
    result: ToolExecutionResult | None = None
    error: str | None = None


class ActionExecutionCoordinator:
    def __init__(
        self,
        *,
        database: Database,
        actions: ActionRepository,
        runs: RunRepository,
        run_coordinator: RunCoordinator,
        ledger: EventLedger,
        policy: SupervisedPolicy,
    ) -> None:
        self.database = database
        self.actions = actions
        self.runs = runs
        self.run_coordinator = run_coordinator
        self.ledger = ledger
        self.policy = policy

    async def execute(
        self,
        *,
        action_id: str,
        tool: ToolSpec,
        workspace: Workspace,
        executor: ToolExecutor,
    ) -> ActionExecutionOutcome:
        action = await self.actions.get(action_id)
        if action is None:
            raise ActionNotFoundError(action_id)
        decision = self.policy.evaluate(tool, workspace)
        if decision.kind is not DecisionKind.APPROVE:
            raise ApprovalPolicyError(decision.reason)
        if action.tool_id != tool.tool_id:
            raise ApprovalPolicyError("approved action tool does not match frozen ToolSpec")
        if action.status is ActionStatus.EXECUTING:
            return await self._needs_review(action, "recovered ambiguous executing action")
        if action.status is not ActionStatus.APPROVED:
            raise ApprovalPolicyError(f"action is {action.status.value}, not approved")

        async with self.database.transaction() as connection:
            executing = await self.actions.transition_in(
                connection,
                action.id,
                ActionStatus.EXECUTING,
                action.version,
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="action.execution_started",
                    actor=Actor.SYSTEM,
                    stream_kind="action",
                    stream_id=action.id,
                    correlation_id=action.run_id,
                    payload={"tool_id": tool.tool_id},
                ),
            )

        try:
            result = await executor.execute(
                tool,
                action.arguments,
                ToolExecutionContext(
                    run_id=action.run_id,
                    workspace_id=workspace.id,
                    action_id=action.id,
                    idempotency_key=action.idempotency_key,
                ),
            )
        except DefinitiveToolError as error:
            failed = await self._finish(
                executing,
                ActionStatus.FAILED,
                event_type="action.execution_failed",
                error=error,
            )
            return ActionExecutionOutcome(
                status=ActionExecutionStatus.FAILED,
                action=failed,
                error=str(error),
            )
        except Exception as error:
            return await self._needs_review(executing, str(error))

        succeeded = await self._finish(
            executing,
            ActionStatus.SUCCEEDED,
            event_type="action.execution_succeeded",
            result=result,
        )
        return ActionExecutionOutcome(
            status=ActionExecutionStatus.SUCCEEDED,
            action=succeeded,
            result=result,
        )

    async def _finish(
        self,
        action: Action,
        target: ActionStatus,
        *,
        event_type: str,
        result: ToolExecutionResult | None = None,
        error: Exception | None = None,
    ) -> Action:
        async with self.database.transaction() as connection:
            updated = await self.actions.transition_in(
                connection,
                action.id,
                target,
                action.version,
                result=result.output if result else None,
                error_class=type(error).__name__ if error else None,
                error_message=str(error) if error else None,
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type=event_type,
                    actor=Actor.SYSTEM,
                    stream_kind="action",
                    stream_id=action.id,
                    correlation_id=action.run_id,
                    payload={"status": target.value},
                ),
            )
        return updated

    async def _needs_review(self, action: Action, reason: str) -> ActionExecutionOutcome:
        run = await self.runs.get(action.run_id)
        if run is None:
            raise LookupError(action.run_id)
        async with self.database.transaction() as connection:
            updated = await self.actions.transition_in(
                connection,
                action.id,
                ActionStatus.NEEDS_REVIEW,
                action.version,
                error_class="AmbiguousSideEffectError",
                error_message=reason,
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="action.needs_review",
                    actor=Actor.SYSTEM,
                    stream_kind="action",
                    stream_id=action.id,
                    correlation_id=action.run_id,
                    payload={"reason": reason},
                ),
            )
            await self.run_coordinator.transition_in(
                connection,
                run_id=run.id,
                target=RunStatus.NEEDS_REVIEW,
                expected_version=run.version,
                error_class="AmbiguousSideEffectError",
                error_message=reason,
            )
        return ActionExecutionOutcome(
            status=ActionExecutionStatus.NEEDS_REVIEW,
            action=updated,
            error=reason,
        )
