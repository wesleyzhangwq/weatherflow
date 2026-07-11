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
        await connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            await connection.close()

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
