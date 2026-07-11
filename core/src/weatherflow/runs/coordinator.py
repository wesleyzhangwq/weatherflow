from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs.models import Run, RunStatus
from weatherflow.runs.repository import RunNotFoundError, RunRepository
from weatherflow.storage import Database


class RunCoordinator:
    def __init__(
        self,
        database: Database,
        repository: RunRepository,
        ledger: EventLedger,
    ) -> None:
        self.database = database
        self.repository = repository
        self.ledger = ledger

    async def create_run(
        self,
        *,
        client_request_id: str,
        user_intent: str,
        workspace_id: str,
    ) -> Run:
        existing = await self.repository.get_by_client_request_id(client_request_id)
        if existing is not None:
            return existing
        run = Run.new(
            client_request_id=client_request_id,
            user_intent=user_intent,
            workspace_id=workspace_id,
        )
        async with self.database.transaction() as connection:
            existing = await self.repository.get_by_client_request_id_in(
                connection, client_request_id
            )
            if existing is not None:
                return existing
            await self.repository.create_in(connection, run)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="run.created",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=run.id,
                    correlation_id=run.id,
                    payload={
                        "client_request_id": client_request_id,
                        "workspace_id": workspace_id,
                        "status": run.status.value,
                    },
                ),
            )
        return run

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
