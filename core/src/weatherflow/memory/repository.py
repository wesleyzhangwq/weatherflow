import json
import sqlite3
from typing import Any

import aiosqlite

from weatherflow.memory.models import EpisodicMemory, ProfileAssertion
from weatherflow.storage import Database


class DuplicateMemoryError(ValueError):
    pass


class ProfileVersionConflict(RuntimeError):
    pass


class EpisodeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_in(self, connection: aiosqlite.Connection, memory: EpisodicMemory) -> None:
        try:
            await connection.execute(
                """
                INSERT INTO episodic_memories(
                    id, workspace_id, summary, source_event_ids, tags, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.id,
                    memory.workspace_id,
                    memory.summary,
                    _json(memory.source_event_ids),
                    _json(memory.tags),
                    memory.created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise DuplicateMemoryError(memory.id) from error

    async def list_workspace(self, workspace_id: str) -> list[EpisodicMemory]:
        async with self.database.connect() as connection:
            return await self.list_workspace_in(connection, workspace_id)

    async def list_workspace_in(
        self, connection: aiosqlite.Connection, workspace_id: str
    ) -> list[EpisodicMemory]:
        rows = await (
            await connection.execute(
                """
                SELECT * FROM episodic_memories
                WHERE workspace_id = ? ORDER BY created_at, id
                """,
                (workspace_id,),
            )
        ).fetchall()
        return [_episode(row) for row in rows]

    async def get_in(
        self, connection: aiosqlite.Connection, entry_id: str
    ) -> EpisodicMemory | None:
        row = await (
            await connection.execute("SELECT * FROM episodic_memories WHERE id = ?", (entry_id,))
        ).fetchone()
        return _episode(row) if row else None


class ProfileAssertionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_in(
        self, connection: aiosqlite.Connection, assertion: ProfileAssertion
    ) -> None:
        try:
            await connection.execute(
                """
                INSERT INTO profile_assertions(
                    id, workspace_id, claim, confidence, status,
                    evidence_event_ids, origin, version, created_at,
                    last_confirmed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _profile_values(assertion),
            )
        except sqlite3.IntegrityError as error:
            raise DuplicateMemoryError(assertion.id) from error

    async def get(self, assertion_id: str) -> ProfileAssertion | None:
        async with self.database.connect() as connection:
            return await self.get_in(connection, assertion_id)

    async def list_workspace(self, workspace_id: str) -> list[ProfileAssertion]:
        async with self.database.connect() as connection:
            return await self.list_workspace_in(connection, workspace_id)

    async def get_in(
        self, connection: aiosqlite.Connection, assertion_id: str
    ) -> ProfileAssertion | None:
        row = await (
            await connection.execute(
                "SELECT * FROM profile_assertions WHERE id = ?", (assertion_id,)
            )
        ).fetchone()
        return _profile(row) if row else None

    async def list_workspace_in(
        self, connection: aiosqlite.Connection, workspace_id: str
    ) -> list[ProfileAssertion]:
        rows = await (
            await connection.execute(
                """
                SELECT * FROM profile_assertions
                WHERE workspace_id = ? ORDER BY created_at, id
                """,
                (workspace_id,),
            )
        ).fetchall()
        return [_profile(row) for row in rows]

    async def update_in(
        self,
        connection: aiosqlite.Connection,
        assertion: ProfileAssertion,
        *,
        expected_version: int,
    ) -> None:
        cursor = await connection.execute(
            """
            UPDATE profile_assertions SET
                claim = ?, confidence = ?, status = ?, evidence_event_ids = ?,
                version = ?, last_confirmed_at = ?, updated_at = ?
            WHERE id = ? AND version = ?
            """,
            (
                assertion.claim,
                assertion.confidence,
                assertion.status.value,
                _json(assertion.evidence_event_ids),
                assertion.version,
                assertion.last_confirmed_at.isoformat(),
                assertion.updated_at.isoformat(),
                assertion.id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise ProfileVersionConflict(assertion.id)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _episode(row: Any) -> EpisodicMemory:
    return EpisodicMemory.model_validate(
        {
            "id": row["id"],
            "workspace_id": row["workspace_id"],
            "summary": row["summary"],
            "source_event_ids": tuple(json.loads(row["source_event_ids"])),
            "tags": tuple(json.loads(row["tags"])),
            "created_at": row["created_at"],
        }
    )


def _profile_values(assertion: ProfileAssertion) -> tuple[Any, ...]:
    return (
        assertion.id,
        assertion.workspace_id,
        assertion.claim,
        assertion.confidence,
        assertion.status.value,
        _json(assertion.evidence_event_ids),
        assertion.origin,
        assertion.version,
        assertion.created_at.isoformat(),
        assertion.last_confirmed_at.isoformat(),
        assertion.updated_at.isoformat(),
    )


def _profile(row: Any) -> ProfileAssertion:
    return ProfileAssertion.model_validate(
        {
            "id": row["id"],
            "workspace_id": row["workspace_id"],
            "claim": row["claim"],
            "confidence": row["confidence"],
            "status": row["status"],
            "evidence_event_ids": tuple(json.loads(row["evidence_event_ids"])),
            "origin": row["origin"],
            "version": row["version"],
            "created_at": row["created_at"],
            "last_confirmed_at": row["last_confirmed_at"],
            "updated_at": row["updated_at"],
        }
    )
