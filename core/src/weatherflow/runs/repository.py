import sqlite3
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from weatherflow.runs.models import Run, RunBudget, RunStatus
from weatherflow.storage import Database


class DuplicateRunError(ValueError):
    pass


class RunNotFoundError(LookupError):
    pass


class RunVersionConflict(RuntimeError):
    pass


class RunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_in(self, connection: aiosqlite.Connection, run: Run) -> None:
        try:
            await connection.execute(
                """
                INSERT INTO runs(
                    id, client_request_id, user_intent, workspace_id, session_id, tool_mode, status,
                    version, created_at, updated_at, rhythm_snapshot_id,
                    capability_snapshot_id, policy_profile, budget,
                    checkpoint_ref, result_summary, error_class, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(run),
            )
        except sqlite3.IntegrityError as error:
            raise DuplicateRunError(run.client_request_id) from error

    async def get(self, run_id: str) -> Run | None:
        async with self.database.connect() as connection:
            return await self.get_in(connection, run_id)

    async def get_in(self, connection: aiosqlite.Connection, run_id: str) -> Run | None:
        row = await (
            await connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        ).fetchone()
        return self._from_row(row) if row else None

    async def get_by_client_request_id(self, value: str) -> Run | None:
        async with self.database.connect() as connection:
            return await self.get_by_client_request_id_in(connection, value)

    async def list_recent(
        self,
        *,
        limit: int = 50,
        workspace_id: str | None = None,
        session_id: str | None = None,
    ) -> list[Run]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        async with self.database.connect() as connection:
            clauses: list[str] = []
            parameters: list[object] = []
            if workspace_id is not None:
                clauses.append("workspace_id = ?")
                parameters.append(workspace_id)
            if session_id is not None:
                clauses.append("session_id = ?")
                parameters.append(session_id)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            query = "SELECT * FROM runs" + where + " ORDER BY updated_at DESC, id DESC LIMIT ?"
            parameters.append(limit)
            rows = await (await connection.execute(query, tuple(parameters))).fetchall()
        return [self._from_row(row) for row in rows]

    async def get_by_client_request_id_in(
        self, connection: aiosqlite.Connection, value: str
    ) -> Run | None:
        row = await (
            await connection.execute("SELECT * FROM runs WHERE client_request_id = ?", (value,))
        ).fetchone()
        return self._from_row(row) if row else None

    async def transition_in(
        self,
        connection: aiosqlite.Connection,
        run_id: str,
        target: RunStatus,
        expected_version: int,
        *,
        result_summary: str | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> Run:
        current = await self.get_in(connection, run_id)
        if current is None:
            raise RunNotFoundError(run_id)
        if current.version != expected_version:
            raise RunVersionConflict(run_id)
        current.status.require_transition(target)
        updated_at = datetime.now(UTC)
        cursor = await connection.execute(
            """
            UPDATE runs
            SET status = ?, version = version + 1, updated_at = ?,
                result_summary = ?, error_class = ?, error_message = ?
            WHERE id = ? AND version = ?
            """,
            (
                target.value,
                updated_at.isoformat(),
                result_summary,
                error_class,
                error_message,
                run_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise RunVersionConflict(run_id)
        updated = await self.get_in(connection, run_id)
        if updated is None:
            raise RunNotFoundError(run_id)
        return updated

    async def attach_capability_snapshot_in(
        self,
        connection: aiosqlite.Connection,
        run_id: str,
        snapshot_id: str,
        expected_version: int,
    ) -> Run:
        current = await self.get_in(connection, run_id)
        if current is None:
            raise RunNotFoundError(run_id)
        if current.version != expected_version or current.capability_snapshot_id is not None:
            raise RunVersionConflict(run_id)
        cursor = await connection.execute(
            """
            UPDATE runs
            SET capability_snapshot_id = ?, version = version + 1, updated_at = ?
            WHERE id = ? AND version = ? AND capability_snapshot_id IS NULL
            """,
            (snapshot_id, datetime.now(UTC).isoformat(), run_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise RunVersionConflict(run_id)
        updated = await self.get_in(connection, run_id)
        if updated is None:
            raise RunNotFoundError(run_id)
        return updated

    async def attach_rhythm_snapshot_in(
        self,
        connection: aiosqlite.Connection,
        run_id: str,
        snapshot_id: str,
        expected_version: int,
    ) -> Run:
        current = await self.get_in(connection, run_id)
        if current is None:
            raise RunNotFoundError(run_id)
        if current.version != expected_version or current.rhythm_snapshot_id is not None:
            raise RunVersionConflict(run_id)
        cursor = await connection.execute(
            """
            UPDATE runs
            SET rhythm_snapshot_id = ?, version = version + 1, updated_at = ?
            WHERE id = ? AND version = ? AND rhythm_snapshot_id IS NULL
            """,
            (snapshot_id, datetime.now(UTC).isoformat(), run_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise RunVersionConflict(run_id)
        updated = await self.get_in(connection, run_id)
        if updated is None:
            raise RunNotFoundError(run_id)
        return updated

    @staticmethod
    def _values(run: Run) -> tuple[Any, ...]:
        return (
            run.id,
            run.client_request_id,
            run.user_intent,
            run.workspace_id,
            run.session_id,
            run.tool_mode.value,
            run.status.value,
            run.version,
            run.created_at.isoformat(),
            run.updated_at.isoformat(),
            run.rhythm_snapshot_id,
            run.capability_snapshot_id,
            run.policy_profile,
            run.budget.model_dump_json(),
            run.checkpoint_ref,
            run.result_summary,
            run.error_class,
            run.error_message,
        )

    @staticmethod
    def _from_row(row: Any) -> Run:
        return Run.model_validate(
            {
                "id": row["id"],
                "client_request_id": row["client_request_id"],
                "user_intent": row["user_intent"],
                "workspace_id": row["workspace_id"],
                "session_id": row["session_id"],
                "tool_mode": row["tool_mode"],
                "status": row["status"],
                "version": row["version"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "rhythm_snapshot_id": row["rhythm_snapshot_id"],
                "capability_snapshot_id": row["capability_snapshot_id"],
                "policy_profile": row["policy_profile"],
                "budget": RunBudget.model_validate_json(row["budget"]),
                "checkpoint_ref": row["checkpoint_ref"],
                "result_summary": row["result_summary"],
                "error_class": row["error_class"],
                "error_message": row["error_message"],
            }
        )
