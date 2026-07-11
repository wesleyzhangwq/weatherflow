from typing import Any

import aiosqlite
from pydantic import BaseModel, ConfigDict

from weatherflow.capabilities.models import ToolSpec
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs import Run, RunCoordinator, RunRepository, RunStatus
from weatherflow.storage import Database
from weatherflow.trust.action_repository import ActionRepository
from weatherflow.trust.approval_repository import ApprovalNotFoundError, ApprovalRepository
from weatherflow.trust.models import Action, ActionStatus, Approval, ApprovalStatus
from weatherflow.trust.policy import DecisionKind, SupervisedPolicy
from weatherflow.workspaces import Workspace


class ApprovalPolicyError(PermissionError):
    pass


class ApprovalStateError(RuntimeError):
    pass


class ApprovalAlreadyDecided(RuntimeError):
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

    async def decide(
        self,
        *,
        approval_id: str,
        expected_version: int,
        approved: bool,
        decided_by: str,
        rationale: str | None = None,
    ) -> ApprovalBundle:
        target_approval = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
        target_action = ActionStatus.APPROVED if approved else ActionStatus.DENIED
        current = await self.approvals.get(approval_id)
        if current is None:
            raise ApprovalNotFoundError(approval_id)
        if current.status is target_approval:
            return await self._bundle_for_approval(current)
        if current.status is not ApprovalStatus.PENDING:
            raise ApprovalAlreadyDecided(approval_id)

        async with self.database.transaction() as connection:
            current = await self.approvals.get_in(connection, approval_id)
            if current is None:
                raise ApprovalNotFoundError(approval_id)
            if current.status is target_approval:
                return await self._bundle_for_approval_in(connection, current)
            if current.status is not ApprovalStatus.PENDING:
                raise ApprovalAlreadyDecided(approval_id)
            action = await self.actions.get_in(connection, current.action_id)
            run = await self.runs.get_in(connection, current.run_id)
            if action is None or run is None:
                raise ApprovalStateError(approval_id)
            updated_approval = await self.approvals.transition_in(
                connection,
                approval_id,
                target_approval,
                expected_version,
                decided_by=decided_by,
                rationale=rationale,
            )
            updated_action = await self.actions.transition_in(
                connection,
                action.id,
                target_action,
                action.version,
            )
            prior = await self.ledger.list_stream_in(connection, "approval", approval_id)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="approval.decided",
                    actor=Actor.USER if decided_by == "user" else Actor.SYSTEM,
                    stream_kind="approval",
                    stream_id=approval_id,
                    correlation_id=current.run_id,
                    causation_id=prior[-1].id if prior else None,
                    payload={
                        "action_id": action.id,
                        "status": target_approval.value,
                        "decided_by": decided_by,
                        "rationale": rationale,
                    },
                ),
            )
            updated_run = await self.run_coordinator.transition_in(
                connection,
                run_id=run.id,
                target=RunStatus.RUNNING,
                expected_version=run.version,
            )
        return ApprovalBundle(
            action=updated_action,
            approval=updated_approval,
            run=updated_run,
        )

    async def expire(
        self,
        *,
        approval_id: str,
        expected_version: int,
    ) -> ApprovalBundle:
        current = await self.approvals.get(approval_id)
        if current is None:
            raise ApprovalNotFoundError(approval_id)
        if current.status is ApprovalStatus.EXPIRED:
            return await self._bundle_for_approval(current)
        if current.status is not ApprovalStatus.PENDING:
            raise ApprovalAlreadyDecided(approval_id)

        async with self.database.transaction() as connection:
            current = await self.approvals.get_in(connection, approval_id)
            if current is None:
                raise ApprovalNotFoundError(approval_id)
            if current.status is ApprovalStatus.EXPIRED:
                return await self._bundle_for_approval_in(connection, current)
            if current.status is not ApprovalStatus.PENDING:
                raise ApprovalAlreadyDecided(approval_id)
            action = await self.actions.get_in(connection, current.action_id)
            run = await self.runs.get_in(connection, current.run_id)
            if action is None or run is None:
                raise ApprovalStateError(approval_id)
            updated_approval = await self.approvals.transition_in(
                connection,
                approval_id,
                ApprovalStatus.EXPIRED,
                expected_version,
                decided_by="system",
                rationale="approval timeout",
            )
            updated_action = await self.actions.transition_in(
                connection,
                action.id,
                ActionStatus.CANCELLED,
                action.version,
            )
            prior = await self.ledger.list_stream_in(connection, "approval", approval_id)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="approval.expired",
                    actor=Actor.SYSTEM,
                    stream_kind="approval",
                    stream_id=approval_id,
                    correlation_id=current.run_id,
                    causation_id=prior[-1].id if prior else None,
                    payload={"action_id": action.id},
                ),
            )
            updated_run = await self.run_coordinator.transition_in(
                connection,
                run_id=run.id,
                target=RunStatus.PAUSED,
                expected_version=run.version,
            )
        return ApprovalBundle(
            action=updated_action,
            approval=updated_approval,
            run=updated_run,
        )

    async def _bundle_for_approval(self, approval: Approval) -> ApprovalBundle:
        action = await self.actions.get(approval.action_id)
        run = await self.runs.get(approval.run_id)
        if action is None or run is None:
            raise ApprovalStateError(approval.id)
        return ApprovalBundle(action=action, approval=approval, run=run)

    async def _bundle_for_approval_in(
        self, connection: aiosqlite.Connection, approval: Approval
    ) -> ApprovalBundle:
        action = await self.actions.get_in(connection, approval.action_id)
        run = await self.runs.get_in(connection, approval.run_id)
        if action is None or run is None:
            raise ApprovalStateError(approval.id)
        return ApprovalBundle(action=action, approval=approval, run=run)

    async def _bundle_in(self, connection: aiosqlite.Connection, action: Action) -> ApprovalBundle:
        approval = await self.approvals.get_by_action_id_in(connection, action.id)
        run = await self.runs.get_in(connection, action.run_id)
        if approval is None or run is None:
            raise ApprovalStateError(action.id)
        return ApprovalBundle(action=action, approval=approval, run=run)
