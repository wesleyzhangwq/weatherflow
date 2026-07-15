import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from weatherflow.connectors import ConnectorAccount, ConnectorBinding, ConnectorKind
from weatherflow.extensions import CredentialRef
from weatherflow.storage.database import Database
from weatherflow.storage.migrations import MIGRATIONS
from weatherflow.workspaces import Workspace, WorkspaceRepository


async def initialize_through(path: Path, version: int) -> None:
    async with aiosqlite.connect(path) as connection:
        await connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await connection.commit()
        for migration in MIGRATIONS:
            if migration.version > version:
                break
            await connection.executescript(
                "BEGIN IMMEDIATE;\n"
                f"{migration.sql}\n"
                "INSERT INTO schema_migrations(version) "
                f"VALUES ({migration.version});\n"
                "COMMIT;"
            )


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
                "'automations', 'automation_run_links', 'mcp_connections', "
                "'run_connector_routes', 'conversation_sessions', 'run_controls') "
                "ORDER BY name"
            )
        ).fetchall()

    assert journal_mode == ("wal",)
    assert migration == (21,)
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
        ("conversation_sessions",),
        ("episodic_memories",),
        ("events",),
        ("mcp_connections",),
        ("memory_search_index",),
        ("model_configurations",),
        ("onboarding_preferences",),
        ("profile_assertions",),
        ("provider_continuations",),
        ("rhythm_snapshots",),
        ("run_connector_routes",),
        ("run_controls",),
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

    assert tuple(count) == (21,)


async def test_migration_20_scopes_legacy_connector_accounts_and_routes_by_workspace(
    tmp_path: Path,
) -> None:
    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 19)
    database = Database(path)
    first = Workspace.new(
        name="First",
        action_roots=[tmp_path / "first"],
        internal_root=tmp_path / "first-internal",
        artifact_root=tmp_path / "first-artifacts",
    )
    second = Workspace.new(
        name="Second",
        action_roots=[tmp_path / "second"],
        internal_root=tmp_path / "second-internal",
        artifact_root=tmp_path / "second-artifacts",
    )
    workspaces = WorkspaceRepository(database)
    await workspaces.create(first)
    await workspaces.create(second)
    now = datetime.now(UTC)
    account = ConnectorAccount.new(
        workspace_id=first.id,
        connector=ConnectorKind.GITHUB,
        external_account_id="ca_legacy",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now,
    ).activate(now=now)
    legacy_account = json.loads(account.model_dump_json())
    legacy_account.pop("workspace_id")
    first_binding = ConnectorBinding.new(
        workspace_id=first.id,
        connector=ConnectorKind.GITHUB,
        account_id=account.id,
        now=now,
    )
    second_binding = ConnectorBinding.new(
        workspace_id=second.id,
        connector=ConnectorKind.GITHUB,
        account_id=account.id,
        now=now,
    )
    async with database.transaction() as connection:
        await connection.execute(
            """
            INSERT INTO connector_accounts(
                id, connector, external_account_id, phase, config,
                version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account.id,
                account.connector.value,
                account.external_account_id,
                account.phase.value,
                json.dumps(legacy_account),
                account.version,
                account.created_at.isoformat(),
                account.updated_at.isoformat(),
            ),
        )
        for binding in (first_binding, second_binding):
            await connection.execute(
                """
                INSERT INTO connector_bindings(
                    workspace_id, connector, account_id, enabled, auto_fetch_enabled,
                    next_sync_at, config, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    binding.workspace_id,
                    binding.connector.value,
                    binding.account_id,
                    int(binding.enabled),
                    int(binding.auto_fetch_enabled),
                    binding.next_sync_at.isoformat(),
                    binding.model_dump_json(),
                    binding.version,
                    binding.created_at.isoformat(),
                    binding.updated_at.isoformat(),
                ),
            )
        await connection.execute(
            """
            INSERT INTO runs(
                id, client_request_id, user_intent, workspace_id, status, version,
                created_at, updated_at, policy_profile, budget
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-run",
                "legacy-request",
                "inspect",
                second.id,
                "queued",
                0,
                now.isoformat(),
                now.isoformat(),
                "supervised",
                "{}",
            ),
        )
        await connection.execute(
            """
            INSERT INTO run_connector_routes(
                run_id, workspace_id, connector, account_id,
                external_account_id, conversation_grant_revision, bound_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-run",
                second.id,
                ConnectorKind.GITHUB.value,
                account.id,
                account.external_account_id,
                1,
                now.isoformat(),
            ),
        )

    await database.initialize()

    async with database.connect() as connection:
        accounts = await (
            await connection.execute(
                "SELECT id, workspace_id, config FROM connector_accounts ORDER BY workspace_id"
            )
        ).fetchall()
        bindings = await (
            await connection.execute(
                "SELECT workspace_id, account_id FROM connector_bindings ORDER BY workspace_id"
            )
        ).fetchall()
        route = await (
            await connection.execute(
                "SELECT workspace_id, account_id FROM run_connector_routes WHERE run_id = ?",
                ("legacy-run",),
            )
        ).fetchone()

    assert len(accounts) == 2
    migrated_workspaces = {
        ConnectorAccount.model_validate_json(row["config"]).workspace_id for row in accounts
    }
    assert migrated_workspaces == {first.id, second.id}
    account_by_workspace = {str(row["workspace_id"]): str(row["account_id"]) for row in bindings}
    assert account_by_workspace[first.id] != account_by_workspace[second.id]
    assert route is not None
    assert str(route["workspace_id"]) == second.id
    assert str(route["account_id"]) == account_by_workspace[second.id]
