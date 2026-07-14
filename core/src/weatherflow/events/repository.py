import json
import sqlite3
from collections.abc import Sequence
from typing import Any

import aiosqlite

from weatherflow.events.models import Event
from weatherflow.storage import Database


class DuplicateEventError(ValueError):
    pass


class UnknownEventCursor(LookupError):
    pass


class EventLedger:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def append(self, event: Event) -> None:
        async with self.database.transaction() as connection:
            await self.append_in(connection, event)

    async def append_in(self, connection: aiosqlite.Connection, event: Event) -> None:
        try:
            await connection.execute(
                """
                INSERT INTO events(
                    id, type, recorded_at, actor, stream_kind, stream_id,
                    correlation_id, causation_id, payload, sensitivity,
                    retention_class
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(event),
            )
        except sqlite3.IntegrityError as error:
            raise DuplicateEventError(event.id) from error

    @staticmethod
    def _values(event: Event) -> tuple[Any, ...]:
        return (
            event.id,
            event.type,
            event.recorded_at.isoformat(),
            event.actor.value,
            event.stream_kind,
            event.stream_id,
            event.correlation_id,
            event.causation_id,
            json.dumps(event.payload, ensure_ascii=False, separators=(",", ":")),
            event.sensitivity.value,
            event.retention_class.value,
        )

    async def get(self, event_id: str) -> Event | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute("SELECT * FROM events WHERE id = ?", (event_id,))
            ).fetchone()
        return self._from_row(row) if row else None

    async def list_stream(
        self,
        stream_kind: str,
        stream_id: str,
        *,
        limit: int = 100,
    ) -> list[Event]:
        return await self._list(
            "stream_kind = ? AND stream_id = ?",
            (stream_kind, stream_id),
            limit,
        )

    async def list_stream_recent(
        self,
        stream_kind: str,
        stream_id: str,
        *,
        limit: int = 100,
    ) -> list[Event]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT * FROM events
                    WHERE stream_kind = ? AND stream_id = ?
                    ORDER BY recorded_at DESC, id DESC LIMIT ?
                    """,
                    (stream_kind, stream_id, limit),
                )
            ).fetchall()
        return [self._from_row(row) for row in rows]

    async def list_stream_in(
        self,
        connection: aiosqlite.Connection,
        stream_kind: str,
        stream_id: str,
        *,
        limit: int = 100,
    ) -> list[Event]:
        return await self._list_in(
            connection,
            "stream_kind = ? AND stream_id = ?",
            (stream_kind, stream_id),
            limit,
        )

    async def list_correlation(
        self,
        correlation_id: str,
        *,
        limit: int = 100,
    ) -> list[Event]:
        return await self._list("correlation_id = ?", (correlation_id,), limit)

    async def list_after(self, cursor: str | None, *, limit: int = 100) -> list[Event]:
        async with self.database.connect() as connection:
            return await self.list_after_in(connection, cursor, limit=limit)

    async def list_after_in(
        self,
        connection: aiosqlite.Connection,
        cursor: str | None,
        *,
        limit: int = 100,
    ) -> list[Event]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if cursor is None:
            rows = await (
                await connection.execute(
                    "SELECT * FROM events ORDER BY recorded_at, id LIMIT ?", (limit,)
                )
            ).fetchall()
            return [self._from_row(row) for row in rows]
        cursor_row = await (
            await connection.execute("SELECT recorded_at, id FROM events WHERE id = ?", (cursor,))
        ).fetchone()
        if cursor_row is None:
            raise UnknownEventCursor(cursor)
        rows = await (
            await connection.execute(
                """
                SELECT * FROM events
                WHERE recorded_at > ? OR (recorded_at = ? AND id > ?)
                ORDER BY recorded_at, id LIMIT ?
                """,
                (
                    cursor_row["recorded_at"],
                    cursor_row["recorded_at"],
                    cursor_row["id"],
                    limit,
                ),
            )
        ).fetchall()
        return [self._from_row(row) for row in rows]

    async def _list(
        self,
        where: str,
        parameters: Sequence[Any],
        limit: int,
    ) -> list[Event]:
        async with self.database.connect() as connection:
            return await self._list_in(connection, where, parameters, limit)

    async def _list_in(
        self,
        connection: aiosqlite.Connection,
        where: str,
        parameters: Sequence[Any],
        limit: int,
    ) -> list[Event]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        query = f"SELECT * FROM events WHERE {where} ORDER BY recorded_at, id LIMIT ?"
        rows = await (await connection.execute(query, (*parameters, limit))).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: Any) -> Event:
        return Event.model_validate(
            {
                "id": row["id"],
                "type": row["type"],
                "recorded_at": row["recorded_at"],
                "actor": row["actor"],
                "stream_kind": row["stream_kind"],
                "stream_id": row["stream_id"],
                "correlation_id": row["correlation_id"],
                "causation_id": row["causation_id"],
                "payload": json.loads(row["payload"]),
                "sensitivity": row["sensitivity"],
                "retention_class": row["retention_class"],
            }
        )
