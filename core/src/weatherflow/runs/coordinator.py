import aiosqlite

from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs.models import Run, RunBudget, RunStatus, ToolMode
from weatherflow.runs.repository import RunNotFoundError, RunRepository
from weatherflow.sessions import ConversationSessionRepository
from weatherflow.storage import Database


class RunIdempotencyConflict(RuntimeError):
    pass


class RunCoordinator:
    def __init__(
        self,
        database: Database,
        repository: RunRepository,
        ledger: EventLedger,
        sessions: ConversationSessionRepository | None = None,
    ) -> None:
        self.database = database
        self.repository = repository
        self.ledger = ledger
        self.sessions = sessions

    async def create_run(
        self,
        *,
        client_request_id: str,
        user_intent: str,
        workspace_id: str,
        session_id: str | None = None,
        tool_mode: ToolMode = ToolMode.ASK,
        budget: RunBudget | None = None,
    ) -> Run:
        existing = await self.repository.get_by_client_request_id(client_request_id)
        if existing is not None:
            self._require_idempotency_scope(
                existing,
                workspace_id=workspace_id,
                session_id=session_id,
                tool_mode=tool_mode,
            )
            return existing
        run = Run.new(
            client_request_id=client_request_id,
            user_intent=user_intent,
            workspace_id=workspace_id,
            session_id=session_id,
            tool_mode=tool_mode,
            budget=budget,
        )
        async with self.database.transaction() as connection:
            existing = await self.repository.get_by_client_request_id_in(
                connection, client_request_id
            )
            if existing is not None:
                self._require_idempotency_scope(
                    existing,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    tool_mode=tool_mode,
                )
                return existing
            if session_id is not None:
                if self.sessions is None:
                    raise LookupError(session_id)
                await self.sessions.require_workspace_in(
                    connection,
                    session_id=session_id,
                    workspace_id=workspace_id,
                )
            await self.repository.create_in(connection, run)
            if session_id is not None:
                assert self.sessions is not None
                await self.sessions.touch_for_run_in(
                    connection,
                    session_id=session_id,
                    workspace_id=workspace_id,
                    observed_at=run.updated_at,
                )
            payload = {
                "client_request_id": client_request_id,
                "workspace_id": workspace_id,
                "tool_mode": tool_mode.value,
                "status": run.status.value,
            }
            if session_id is not None:
                payload["session_id"] = session_id
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="run.created",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=run.id,
                    correlation_id=run.id,
                    payload=payload,
                ),
            )
        return run

    @staticmethod
    def _require_idempotency_scope(
        existing: Run,
        *,
        workspace_id: str,
        session_id: str | None,
        tool_mode: ToolMode,
    ) -> None:
        if (
            existing.workspace_id != workspace_id
            or existing.session_id != session_id
            or existing.tool_mode is not tool_mode
        ):
            raise RunIdempotencyConflict(existing.client_request_id)

    async def transition(
        self,
        *,
        run_id: str,
        target: RunStatus,
        expected_version: int,
        result_summary: str | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> Run:
        async with self.database.transaction() as connection:
            return await self.transition_in(
                connection,
                run_id=run_id,
                target=target,
                expected_version=expected_version,
                result_summary=result_summary,
                error_class=error_class,
                error_message=error_message,
            )

    async def transition_in(
        self,
        connection: aiosqlite.Connection,
        *,
        run_id: str,
        target: RunStatus,
        expected_version: int,
        result_summary: str | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> Run:
        current = await self.repository.get_in(connection, run_id)
        if current is None:
            raise RunNotFoundError(run_id)
        prior = await self.ledger.list_stream_in(connection, "run", run_id)
        updated = await self.repository.transition_in(
            connection,
            run_id,
            target,
            expected_version,
            result_summary=result_summary,
            error_class=error_class,
            error_message=error_message,
        )
        await self.ledger.append_in(
            connection,
            Event.new(
                type="run.status_changed",
                actor=Actor.SYSTEM,
                stream_kind="run",
                stream_id=run_id,
                correlation_id=run_id,
                causation_id=prior[-1].id if prior else None,
                payload={
                    "from": current.status.value,
                    "to": target.value,
                    "version": updated.version,
                },
            ),
        )
        return updated
