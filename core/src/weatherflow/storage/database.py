from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from weatherflow.storage.migrations import MIGRATIONS


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await aiosqlite.connect(self.path)
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA busy_timeout = 5000")
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute("PRAGMA secure_delete = ON")
        try:
            yield connection
        finally:
            await connection.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                await connection.rollback()
                raise
            else:
                await connection.commit()

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as connection:
            await connection.execute("PRAGMA journal_mode = WAL")
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            rows = await (
                await connection.execute("SELECT version FROM schema_migrations")
            ).fetchall()
            applied = {int(row["version"]) for row in rows}
            await connection.commit()
            for migration in MIGRATIONS:
                if migration.version in applied:
                    continue
                await connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    f"{migration.sql}\n"
                    "INSERT INTO schema_migrations(version) "
                    f"VALUES ({migration.version});\n"
                    "COMMIT;"
                )
            compaction = await (
                await connection.execute(
                    """
                    SELECT 1
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'privacy_compaction_requests'
                    """
                )
            ).fetchone()
            if compaction is not None:
                requested = await (
                    await connection.execute(
                        "SELECT 1 FROM privacy_compaction_requests WHERE id = 1"
                    )
                ).fetchone()
                if requested is not None:
                    await self._compact_in(connection)
                    await connection.execute("DELETE FROM privacy_compaction_requests WHERE id = 1")
                    await connection.commit()
                    await self._checkpoint_in(connection)

    async def secure_compact(self) -> None:
        """Remove deleted sensitive content from free pages and the WAL."""

        async with self.connect() as connection:
            await self._compact_in(connection)

    @staticmethod
    async def _checkpoint_in(connection: aiosqlite.Connection) -> None:
        cursor = await connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await cursor.fetchone()
        await cursor.close()

    @classmethod
    async def _compact_in(cls, connection: aiosqlite.Connection) -> None:
        await connection.commit()
        await cls._checkpoint_in(connection)
        await connection.execute("VACUUM")
        await cls._checkpoint_in(connection)
