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
                "('events', 'actions', 'approvals', 'capability_snapshots', "
                "'artifacts', 'checkpoints', 'workspaces', 'rhythm_snapshots', "
                "'episodic_memories', 'profile_assertions', 'memory_search_index', "
                "'checkpoint_quarantine', 'onboarding_preferences', "
                "'model_configurations', 'connector_accounts', "
                "'connector_installation', 'connection_attempts', "
                "'connector_bindings', 'connector_snapshots', "
                "'provider_continuations', 'run_model_routes', "
                "'automations', 'automation_run_links', 'mcp_connections') "
                "ORDER BY name"
            )
        ).fetchall()

    assert journal_mode == ("wal",)
    assert migration == (17,)
    assert tables == [
        ("actions",),
        ("approvals",),
        ("artifacts",),
        ("automation_run_links",),
        ("automations",),
        ("capability_snapshots",),
        ("checkpoint_quarantine",),
        ("checkpoints",),
        ("connection_attempts",),
        ("connector_accounts",),
        ("connector_bindings",),
        ("connector_installation",),
        ("connector_snapshots",),
        ("episodic_memories",),
        ("events",),
        ("mcp_connections",),
        ("memory_search_index",),
        ("model_configurations",),
        ("onboarding_preferences",),
        ("profile_assertions",),
        ("provider_continuations",),
        ("rhythm_snapshots",),
        ("run_model_routes",),
        ("workspaces",),
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

    assert tuple(count) == (17,)
