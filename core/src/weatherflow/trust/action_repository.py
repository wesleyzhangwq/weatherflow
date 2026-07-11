import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from weatherflow.storage import Database
from weatherflow.trust.models import Action, ActionStatus


class DuplicateActionError(ValueError):
    pass


class ActionNotFoundError(LookupError):
    pass


class ActionVersionConflict(RuntimeError):
    pass


class ActionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_in(self, connection: aiosqlite.Connection, action: Action) -> None:
        try:
            await connection.execute(
                """
                INSERT INTO actions(
                    id, run_id, tool_id, arguments, effect, status,
                    idempotency_key, preview, created_at, updated_at, version,
                    result, error_class, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(action),
            )
        except sqlite3.IntegrityError as error:
            if "UNIQUE constraint failed" in str(error):
                raise DuplicateActionError(action.idempotency_key) from error
            raise

    async def get(self, action_id: str) -> Action | None:
        async with self.database.connect() as connection:
            return await self.get_in(connection, action_id)

    async def get_in(self, connection: aiosqlite.Connection, action_id: str) -> Action | None:
        row = await (
            await connection.execute("SELECT * FROM actions WHERE id = ?", (action_id,))
        ).fetchone()
        return self._from_row(row) if row else None

    async def get_by_idempotency_key(self, value: str) -> Action | None:
        async with self.database.connect() as connection:
            return await self.get_by_idempotency_key_in(connection, value)

    async def get_by_idempotency_key_in(
        self, connection: aiosqlite.Connection, value: str
    ) -> Action | None:
        row = await (
            await connection.execute("SELECT * FROM actions WHERE idempotency_key = ?", (value,))
        ).fetchone()
        return self._from_row(row) if row else None

    async def transition_in(
        self,
        connection: aiosqlite.Connection,
        action_id: str,
        target: ActionStatus,
        expected_version: int,
        *,
        result: dict[str, Any] | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> Action:
        current = await self.get_in(connection, action_id)
        if current is None:
            raise ActionNotFoundError(action_id)
        if current.version != expected_version:
            raise ActionVersionConflict(action_id)
        current.status.require_transition(target)
        cursor = await connection.execute(
            """
            UPDATE actions
            SET status = ?, updated_at = ?, version = version + 1,
                result = ?, error_class = ?, error_message = ?
            WHERE id = ? AND version = ?
            """,
            (
                target.value,
                datetime.now(UTC).isoformat(),
                self._json(result) if result is not None else None,
                error_class,
                error_message,
                action_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise ActionVersionConflict(action_id)
        updated = await self.get_in(connection, action_id)
        if updated is None:
            raise ActionNotFoundError(action_id)
        return updated

    @classmethod
    def _values(cls, action: Action) -> tuple[Any, ...]:
        return (
            action.id,
            action.run_id,
            action.tool_id,
            cls._json(action.arguments),
            action.effect.value,
            action.status.value,
            action.idempotency_key,
            cls._json(action.preview),
            action.created_at.isoformat(),
            action.updated_at.isoformat(),
            action.version,
            cls._json(action.result) if action.result is not None else None,
            action.error_class,
            action.error_message,
        )

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _from_row(row: Any) -> Action:
        return Action.model_validate(
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "tool_id": row["tool_id"],
                "arguments": json.loads(row["arguments"]),
                "effect": row["effect"],
                "status": row["status"],
                "idempotency_key": row["idempotency_key"],
                "preview": json.loads(row["preview"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "version": row["version"],
                "result": json.loads(row["result"]) if row["result"] else None,
                "error_class": row["error_class"],
                "error_message": row["error_message"],
            }
        )
