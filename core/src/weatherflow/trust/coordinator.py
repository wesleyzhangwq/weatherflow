from typing import Any

import aiosqlite
from pydantic import BaseModel, ConfigDict

from weatherflow.capabilities import ToolSpec
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs import Run, RunCoordinator, RunRepository, RunStatus
from weatherflow.storage import Database
from weatherflow.trust.action_repository import ActionRepository
from weatherflow.trust.approval_repository import ApprovalRepository
from weatherflow.trust.models import Action, Approval
from weatherflow.trust.policy import DecisionKind, SupervisedPolicy
from weatherflow.workspaces import Workspace


class ApprovalPolicyError(PermissionError):
    pass


class ApprovalStateError(RuntimeError):
    pass


class ApprovalBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: Action
    approval: Approval
    run: Run


class ApprovalCoordinator:
    def __init__(
        self,
        *,
        database: Database,
        actions: ActionRepository,
        approvals: ApprovalRepository,
        runs: RunRepository,
        run_coordinator: RunCoordinator,
        ledger: EventLedger,
        policy: SupervisedPolicy,
    ) -> None:
        self.database = database
        self.actions = actions
        self.approvals = approvals
        self.runs = runs
        self.run_coordinator = run_coordinator
        self.ledger = ledger
        self.policy = policy

    async def propose(
        self,
        *,
        run_id: str,
        expected_run_version: int,
        tool: ToolSpec,
        workspace: Workspace,
        arguments: dict[str, Any],
        idempotency_key: str,
        preview: dict[str, Any],
    ) -> ApprovalBundle:
        existing = await self.actions.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return await self._bundle(existing)
        decision = self.policy.evaluate(tool, workspace)
        if decision.kind is not DecisionKind.APPROVE:
            raise ApprovalPolicyError(
                f"tool {tool.tool_id} received {decision.kind.value}, not approve"
            )
        action = Action.new(
            run_id=run_id,
            tool_id=tool.tool_id,
            arguments=arguments,
            effect=tool.effect,
            idempotency_key=idempotency_key,
            preview=preview,
        )
        approval = Approval.for_action(action)
        async with self.database.transaction() as connection:
            existing = await self.actions.get_by_idempotency_key_in(connection, idempotency_key)
            if existing is not None:
                return await self._bundle_in(connection, existing)
            prior = await self.ledger.list_stream_in(connection, "run", run_id)
            await self.actions.create_in(connection, action)
            await self.approvals.create_in(connection, approval)
            action_event = Event.new(
                type="action.proposed",
                actor=Actor.AGENT,
                stream_kind="action",
                stream_id=action.id,
                correlation_id=run_id,
                causation_id=prior[-1].id if prior else None,
                payload={
                    "tool_id": tool.tool_id,
                    "effect": tool.effect.value,
                    "idempotency_key": idempotency_key,
                    "preview": preview,
                },
            )
            await self.ledger.append_in(connection, action_event)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="approval.requested",
                    actor=Actor.SYSTEM,
                    stream_kind="approval",
                    stream_id=approval.id,
                    correlation_id=run_id,
                    causation_id=action_event.id,
                    payload={"action_id": action.id, "tool_id": tool.tool_id},
                ),
            )
            updated_run = await self.run_coordinator.transition_in(
                connection,
                run_id=run_id,
                target=RunStatus.WAITING_APPROVAL,
                expected_version=expected_run_version,
            )
        return ApprovalBundle(action=action, approval=approval, run=updated_run)

    async def _bundle(self, action: Action) -> ApprovalBundle:
        approval = await self.approvals.get_by_action_id(action.id)
        run = await self.runs.get(action.run_id)
        if approval is None or run is None:
            raise ApprovalStateError(action.id)
        return ApprovalBundle(action=action, approval=approval, run=run)

    async def _bundle_in(self, connection: aiosqlite.Connection, action: Action) -> ApprovalBundle:
        approval = await self.approvals.get_by_action_id_in(connection, action.id)
        run = await self.runs.get_in(connection, action.run_id)
        if approval is None or run is None:
            raise ApprovalStateError(action.id)
        return ApprovalBundle(action=action, approval=approval, run=run)
