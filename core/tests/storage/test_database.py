from pathlib import Path

import aiosqlite

from weatherflow.storage.database import Database


async def test_initialize_creates_versioned_wal_database(tmp_path: Path) -> None:
    path = tmp_path / "weatherflow.db"
    database = Database(path)

    await database.initialize()

    assert path.is_file()
    async with aiosqlite.connect(path) as connection:
        journal_mode = await (await connection.execute("PRAGMA journal_mode")).fetchone()
        migration = await (
            await connection.execute("SELECT MAX(version) FROM schema_migrations")
        ).fetchone()
        tables = await (
            await connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name IN "
                "('events', 'actions', 'approvals', 'capability_snapshots') "
                "ORDER BY name"
            )
        ).fetchall()

    assert journal_mode == ("wal",)
    assert migration == (4,)
    assert tables == [
        ("actions",),
        ("approvals",),
        ("capability_snapshots",),
        ("events",),
    ]


async def test_connection_enables_foreign_keys(tmp_path: Path) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()

    async with database.connect() as connection:
        foreign_keys = await (await connection.execute("PRAGMA foreign_keys")).fetchone()

    assert tuple(foreign_keys) == (1,)


async def test_initialize_is_idempotent(tmp_path: Path) -> None:
    database = Database(tmp_path / "weatherflow.db")

    await database.initialize()
    await database.initialize()

    async with database.connect() as connection:
        count = await (
            await connection.execute("SELECT COUNT(*) FROM schema_migrations")
        ).fetchone()

    assert tuple(count) == (4,)
