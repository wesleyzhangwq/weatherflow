import sqlite3
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from weatherflow.sessions.models import (
    ConversationSession,
    ConversationSessionDeletion,
    SessionArtifactBlob,
)
from weatherflow.storage import Database


class SessionNotFoundError(LookupError):
    pass


class SessionVersionConflict(RuntimeError):
    pass


class ConversationSessionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(self, session: ConversationSession) -> None:
        try:
            async with self.database.transaction() as connection:
                await self.create_in(connection, session)
        except sqlite3.IntegrityError as error:
            raise ValueError(f"conversation session could not be created: {session.id}") from error

    async def create_in(
        self,
        connection: aiosqlite.Connection,
        session: ConversationSession,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO conversation_sessions(
                id, workspace_id, title, pinned, version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.workspace_id,
                session.title,
                int(session.pinned),
                session.version,
                session.created_at.isoformat(),
                session.updated_at.isoformat(),
            ),
        )

    async def get(self, session_id: str) -> ConversationSession | None:
        async with self.database.connect() as connection:
            return await self.get_in(connection, session_id)

    async def get_for_workspace(
        self,
        session_id: str,
        workspace_id: str,
    ) -> ConversationSession | None:
        async with self.database.connect() as connection:
            return await self.get_for_workspace_in(connection, session_id, workspace_id)

    async def get_in(
        self,
        connection: aiosqlite.Connection,
        session_id: str,
    ) -> ConversationSession | None:
        row = await (
            await connection.execute(self._select() + " WHERE s.id = ?", (session_id,))
        ).fetchone()
        return self._from_row(row) if row else None

    async def get_for_workspace_in(
        self,
        connection: aiosqlite.Connection,
        session_id: str,
        workspace_id: str,
    ) -> ConversationSession | None:
        row = await (
            await connection.execute(
                self._select() + " WHERE s.id = ? AND s.workspace_id = ?",
                (session_id, workspace_id),
            )
        ).fetchone()
        return self._from_row(row) if row else None

    async def list(
        self,
        workspace_id: str,
        *,
        limit: int = 200,
    ) -> list[ConversationSession]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    self._select()
                    + " WHERE s.workspace_id = ?"
                    + " ORDER BY s.pinned DESC, s.updated_at DESC, s.id DESC LIMIT ?",
                    (workspace_id, limit),
                )
            ).fetchall()
        return [self._from_row(row) for row in rows]

    async def list_run_ids(self, session_id: str, *, workspace_id: str) -> tuple[str, ...]:
        async with self.database.connect() as connection:
            if await self.get_for_workspace_in(connection, session_id, workspace_id) is None:
                raise SessionNotFoundError(session_id)
            rows = await (
                await connection.execute(
                    """
                    SELECT id FROM runs
                    WHERE session_id = ? AND workspace_id = ?
                    ORDER BY created_at, id
                    """,
                    (session_id, workspace_id),
                )
            ).fetchall()
        return tuple(row["id"] for row in rows)

    async def delete(
        self,
        session_id: str,
        *,
        workspace_id: str,
    ) -> ConversationSessionDeletion:
        """Delete one conversation and every Run-owned durable record atomically."""

        async with self.database.transaction() as connection:
            if await self.get_for_workspace_in(connection, session_id, workspace_id) is None:
                raise SessionNotFoundError(session_id)
            run_rows = await (
                await connection.execute(
                    """
                    SELECT id FROM runs
                    WHERE session_id = ? AND workspace_id = ?
                    ORDER BY created_at, id
                    """,
                    (session_id, workspace_id),
                )
            ).fetchall()
            run_ids = tuple(row["id"] for row in run_rows)
            artifact_rows = await (
                await connection.execute(
                    """
                    SELECT DISTINCT a.digest, a.relative_path
                    FROM artifacts AS a
                    JOIN runs AS r ON r.id = a.run_id
                    WHERE r.session_id = ? AND r.workspace_id = ?
                    ORDER BY a.digest, a.relative_path
                    """,
                    (session_id, workspace_id),
                )
            ).fetchall()
            artifacts = tuple(
                SessionArtifactBlob(
                    digest=row["digest"],
                    relative_path=row["relative_path"],
                )
                for row in artifact_rows
            )
            if run_ids:
                placeholders = ",".join("?" for _ in run_ids)
                for table in (
                    "approvals",
                    "actions",
                    "capability_snapshots",
                    "artifacts",
                    "checkpoints",
                    "checkpoint_quarantine",
                    "provider_continuations",
                    "automation_run_links",
                ):
                    await connection.execute(
                        f"DELETE FROM {table} WHERE run_id IN ({placeholders})",
                        run_ids,
                    )
                await connection.execute(
                    f"""
                    WITH RECURSIVE deleted_events(id) AS (
                        SELECT id FROM events
                        WHERE stream_id IN ({placeholders})
                           OR correlation_id IN ({placeholders})
                        UNION
                        SELECT event.id FROM events AS event
                        JOIN deleted_events AS parent
                          ON event.causation_id = parent.id
                    )
                    DELETE FROM events WHERE id IN (SELECT id FROM deleted_events)
                    """,
                    (*run_ids, *run_ids),
                )
                await connection.execute(
                    f"DELETE FROM runs WHERE id IN ({placeholders}) AND workspace_id = ?",
                    (*run_ids, workspace_id),
                )
            cursor = await connection.execute(
                "DELETE FROM conversation_sessions WHERE id = ? AND workspace_id = ?",
                (session_id, workspace_id),
            )
            if cursor.rowcount != 1:
                raise SessionNotFoundError(session_id)
        return ConversationSessionDeletion(
            session_id=session_id,
            workspace_id=workspace_id,
            run_ids=run_ids,
            artifacts=artifacts,
        )

    async def artifact_digest_in_use(
        self,
        digest: str,
        *,
        workspace_id: str,
    ) -> bool:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT 1 FROM artifacts AS a
                    JOIN runs AS r ON r.id = a.run_id
                    WHERE a.digest = ? AND r.workspace_id = ?
                    LIMIT 1
                    """,
                    (digest, workspace_id),
                )
            ).fetchone()
        return row is not None

    async def update(
        self,
        session_id: str,
        *,
        workspace_id: str,
        expected_version: int,
        title: str | None = None,
        pinned: bool | None = None,
    ) -> ConversationSession:
        if title is None and pinned is None:
            raise ValueError("at least one session field must be updated")
        current = await self.get_for_workspace(session_id, workspace_id)
        if current is None:
            raise SessionNotFoundError(session_id)
        normalized = ConversationSession.model_validate(
            {
                **current.model_dump(),
                "title": title if title is not None else current.title,
                "pinned": pinned if pinned is not None else current.pinned,
                "version": current.version + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE conversation_sessions
                SET title = ?, pinned = ?, version = ?, updated_at = ?
                WHERE id = ? AND workspace_id = ? AND version = ?
                """,
                (
                    normalized.title,
                    int(normalized.pinned),
                    normalized.version,
                    normalized.updated_at.isoformat(),
                    session_id,
                    workspace_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                if await self.get_for_workspace_in(connection, session_id, workspace_id) is None:
                    raise SessionNotFoundError(session_id)
                raise SessionVersionConflict(session_id)
            updated = await self.get_for_workspace_in(connection, session_id, workspace_id)
        if updated is None:
            raise SessionNotFoundError(session_id)
        return updated

    async def require_workspace_in(
        self,
        connection: aiosqlite.Connection,
        *,
        session_id: str,
        workspace_id: str,
    ) -> ConversationSession:
        session = await self.get_in(connection, session_id)
        if session is None or session.workspace_id != workspace_id:
            raise SessionNotFoundError(session_id)
        return session

    async def touch_for_run_in(
        self,
        connection: aiosqlite.Connection,
        *,
        session_id: str,
        workspace_id: str,
        observed_at: datetime,
    ) -> None:
        cursor = await connection.execute(
            """
            UPDATE conversation_sessions
            SET version = version + 1, updated_at = ?
            WHERE id = ? AND workspace_id = ?
            """,
            (observed_at.isoformat(), session_id, workspace_id),
        )
        if cursor.rowcount != 1:
            raise SessionNotFoundError(session_id)

    @staticmethod
    def _select() -> str:
        return """
            SELECT s.*,
                (
                    SELECT r.id FROM runs AS r
                    WHERE r.session_id = s.id
                    ORDER BY r.created_at DESC, r.id DESC
                    LIMIT 1
                ) AS latest_run_id
            FROM conversation_sessions AS s
        """

    @staticmethod
    def _from_row(row: Any) -> ConversationSession:
        return ConversationSession.model_validate(
            {
                "id": row["id"],
                "workspace_id": row["workspace_id"],
                "title": row["title"],
                "pinned": bool(row["pinned"]),
                "latest_run_id": row["latest_run_id"],
                "version": row["version"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
