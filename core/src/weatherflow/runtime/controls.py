from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import aiosqlite
from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID

from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs import RunRepository, RunStatus
from weatherflow.runtime.checkpoints import RunCheckpoint
from weatherflow.runtime.models import AgentMessage, MessageRole
from weatherflow.runtime.repository import RunCheckpointRepository
from weatherflow.storage import Database


class RunControlKind(StrEnum):
    STEER = "steer"
    FOLLOW_UP = "follow_up"


class RunControlStatus(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"


class RunControl(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    id: str
    run_id: str
    kind: RunControlKind
    content: str = Field(min_length=1, max_length=20_000)
    status: RunControlStatus
    created_at: datetime
    applied_at: datetime | None = None
    applied_step_index: int | None = Field(default=None, ge=0)

    @classmethod
    def new(
        cls,
        *,
        run_id: str,
        kind: RunControlKind | str,
        content: str,
    ) -> "RunControl":
        return cls(
            id=str(ULID()),
            run_id=run_id,
            kind=RunControlKind(kind),
            content=content,
            status=RunControlStatus.PENDING,
            created_at=datetime.now(UTC),
        )


class RunControlRejectedError(ValueError):
    pass


class RunControlNotFoundError(LookupError):
    pass


class RunControlRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_in(self, connection: aiosqlite.Connection, control: RunControl) -> None:
        await connection.execute(
            """
            INSERT INTO run_controls(
                id, run_id, kind, content, status, created_at,
                applied_at, applied_step_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._values(control),
        )

    async def get(self, control_id: str) -> RunControl | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT * FROM run_controls WHERE id = ?",
                    (control_id,),
                )
            ).fetchone()
        return self._from_row(row) if row else None

    async def list_pending(self, run_id: str) -> list[RunControl]:
        async with self.database.connect() as connection:
            return await self.list_pending_in(connection, run_id)

    async def list_pending_in(
        self,
        connection: aiosqlite.Connection,
        run_id: str,
        *,
        kinds: Iterable[RunControlKind] | None = None,
    ) -> list[RunControl]:
        normalized = tuple(RunControlKind(kind) for kind in kinds) if kinds is not None else ()
        parameters: list[object] = [run_id, RunControlStatus.PENDING.value]
        kind_clause = ""
        if normalized:
            placeholders = ",".join("?" for _ in normalized)
            kind_clause = f" AND kind IN ({placeholders})"
            parameters.extend(kind.value for kind in normalized)
        rows = await (
            await connection.execute(
                """
                SELECT * FROM run_controls
                WHERE run_id = ? AND status = ?
                """
                + kind_clause
                + " ORDER BY created_at, id",
                tuple(parameters),
            )
        ).fetchall()
        return [self._from_row(row) for row in rows]

    async def mark_applied_in(
        self,
        connection: aiosqlite.Connection,
        control_id: str,
        *,
        applied_at: datetime,
        step_index: int,
    ) -> None:
        cursor = await connection.execute(
            """
            UPDATE run_controls
            SET status = ?, applied_at = ?, applied_step_index = ?
            WHERE id = ? AND status = ?
            """,
            (
                RunControlStatus.APPLIED.value,
                applied_at.isoformat(),
                step_index,
                control_id,
                RunControlStatus.PENDING.value,
            ),
        )
        if cursor.rowcount != 1:
            raise RunControlRejectedError(f"control {control_id} is no longer pending")

    @staticmethod
    def _values(control: RunControl) -> tuple[Any, ...]:
        return (
            control.id,
            control.run_id,
            control.kind.value,
            control.content,
            control.status.value,
            control.created_at.isoformat(),
            control.applied_at.isoformat() if control.applied_at else None,
            control.applied_step_index,
        )

    @staticmethod
    def _from_row(row: Any) -> RunControl:
        return RunControl.model_validate(dict(row))


CONTROLLABLE_STATUSES = frozenset(
    {
        RunStatus.QUEUED,
        RunStatus.PLANNING,
        RunStatus.RUNNING,
        RunStatus.WAITING_APPROVAL,
        RunStatus.WAITING_USER,
        RunStatus.PAUSED,
    }
)


class RunControlCoordinator:
    """Durably queues user controls and applies them only at safe turn boundaries."""

    def __init__(
        self,
        *,
        database: Database,
        runs: RunRepository,
        controls: RunControlRepository,
        checkpoints: RunCheckpointRepository,
        ledger: EventLedger,
    ) -> None:
        self.database = database
        self.runs = runs
        self.controls = controls
        self.checkpoints = checkpoints
        self.ledger = ledger

    async def enqueue(
        self,
        *,
        run_id: str,
        kind: RunControlKind | str,
        content: str,
    ) -> RunControl:
        control = RunControl.new(run_id=run_id, kind=kind, content=content)
        async with self.database.transaction() as connection:
            run = await self.runs.get_in(connection, run_id)
            if run is None:
                raise RunControlNotFoundError(run_id)
            if run.status not in CONTROLLABLE_STATUSES:
                raise RunControlRejectedError(
                    f"run {run.id} cannot accept controls while {run.status.value}"
                )
            await self.controls.create_in(connection, control)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="runtime.control_queued",
                    actor=Actor.USER,
                    stream_kind="run",
                    stream_id=run_id,
                    correlation_id=run_id,
                    payload={"control_id": control.id, "kind": control.kind.value},
                ),
            )
        return control

    async def apply_before_model(self, checkpoint: RunCheckpoint) -> RunCheckpoint:
        if checkpoint.state.get("pending_turn") is not None:
            raise RunControlRejectedError("steering requires a clear model boundary")
        async with self.database.transaction() as connection:
            pending = await self.controls.list_pending_in(
                connection,
                checkpoint.run_id,
                kinds=(RunControlKind.STEER,),
            )
            if not pending:
                return checkpoint
            return await self._apply_in(connection, checkpoint, pending)

    async def apply_at_final_boundary_in(
        self,
        connection: aiosqlite.Connection,
        checkpoint: RunCheckpoint,
    ) -> RunCheckpoint | None:
        pending = await self.controls.list_pending_in(connection, checkpoint.run_id)
        if not pending:
            return None
        return await self._apply_in(connection, checkpoint, pending)

    async def _apply_in(
        self,
        connection: aiosqlite.Connection,
        checkpoint: RunCheckpoint,
        pending: list[RunControl],
    ) -> RunCheckpoint:
        state = dict(checkpoint.state)
        state.pop("pending_turn", None)
        state.pop("batch_next_index", None)
        desired = checkpoint.model_copy(
            update={
                "transcript": (
                    *checkpoint.transcript,
                    *(
                        AgentMessage(role=MessageRole.USER, content=control.content)
                        for control in pending
                    ),
                ),
                "state": state,
            }
        )
        saved = await self.checkpoints.save_in(
            connection,
            desired,
            expected_version=checkpoint.version,
        )
        applied_at = datetime.now(UTC)
        for control in pending:
            await self.controls.mark_applied_in(
                connection,
                control.id,
                applied_at=applied_at,
                step_index=saved.step_index,
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="runtime.control_applied",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=checkpoint.run_id,
                    correlation_id=checkpoint.run_id,
                    payload={
                        "control_id": control.id,
                        "kind": control.kind.value,
                        "step_index": saved.step_index,
                    },
                ),
            )
        return saved
