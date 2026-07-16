import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from weatherflow.connectors import (
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
    ConnectorRepository,
)
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
                "'run_connector_routes', 'conversation_sessions', 'run_controls', "
                "'activity_preferences', 'activity_events', "
                "'activity_heartbeat_receipts', 'activity_inference_jobs') "
                "ORDER BY name"
            )
        ).fetchall()

    assert journal_mode == ("wal",)
    assert migration == (26,)
    assert tables == [
        ("actions",),
        ("activity_events",),
        ("activity_heartbeat_receipts",),
        ("activity_inference_jobs",),
        ("activity_preferences",),
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

    assert tuple(count) == (26,)


async def test_migration_26_backfills_activity_source_event_provenance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 25)
    async with aiosqlite.connect(path) as connection:
        await connection.execute(
            """
            INSERT INTO activity_events(
                id, source, device_id, source_instance,
                started_at, ended_at, observed_at, duration_seconds,
                app_name, bundle_id, window_title,
                browser_name, browser_window_id, browser_tab_id,
                url, domain, tab_title, audible, incognito, focused,
                idle_state, category, state_hash, created_at, updated_at
            ) VALUES (
                'event-1', 'macos_window', 'macbook', 'native-main',
                '2026-07-16T06:00:00+00:00', '2026-07-16T06:00:10+00:00',
                '2026-07-16T06:00:10+00:00', 10,
                'Terminal', 'com.apple.Terminal', 'WeatherFlow',
                NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1,
                'active', 'development', 'hash',
                '2026-07-16T06:00:00+00:00', '2026-07-16T06:00:10+00:00'
            )
            """
        )
        await connection.commit()

    await Database(path).initialize()

    async with aiosqlite.connect(path) as connection:
        row = await (
            await connection.execute(
                "SELECT source_event_id FROM activity_events WHERE id = 'event-1'"
            )
        ).fetchone()
    assert row == ("event-1",)


async def test_migration_22_backfills_modes_and_preserves_connector_routes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 21)
    database = Database(path)
    workspace = Workspace.new(
        name="Legacy",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await WorkspaceRepository(database).create(workspace)
    now = datetime.now(UTC).isoformat()
    async with database.transaction() as connection:
        for run_id in ("read-run", "write-run"):
            await connection.execute(
                """
                INSERT INTO runs(
                    id, client_request_id, user_intent, workspace_id, status,
                    version, created_at, updated_at, policy_profile, budget
                ) VALUES (?, ?, 'legacy', ?, 'queued', 0, ?, ?, 'supervised', '{}')
                """,
                (run_id, f"request-{run_id}", workspace.id, now, now),
            )
        await connection.execute(
            """
            INSERT INTO capability_snapshots(
                id, run_id, catalog_revision, tools, digest, created_at
            ) VALUES ('read-snapshot', 'read-run', 'legacy', ?, 'read', ?)
            """,
            (json.dumps([{"effect": "network_read"}]), now),
        )
        await connection.execute(
            """
            INSERT INTO capability_snapshots(
                id, run_id, catalog_revision, tools, digest, created_at
            ) VALUES ('write-snapshot', 'write-run', 'legacy', ?, 'write', ?)
            """,
            (json.dumps([{"effect": "external_write"}]), now),
        )
        await connection.execute(
            """
            INSERT INTO run_connector_routes(
                run_id, workspace_id, connector, account_id,
                external_account_id, conversation_grant_revision, bound_at
            ) VALUES ('write-run', ?, 'github', 'account', 'external', 1, ?)
            """,
            (workspace.id, now),
        )

    await database.initialize()

    async with database.connect() as connection:
        modes = await (
            await connection.execute("SELECT id, tool_mode FROM runs ORDER BY id")
        ).fetchall()
        route = await (
            await connection.execute(
                "SELECT run_id, workspace_id, connector, account_id, external_account_id "
                "FROM run_connector_routes"
            )
        ).fetchone()
        route_columns = {
            str(row[1])
            for row in await (
                await connection.execute("PRAGMA table_info(run_connector_routes)")
            ).fetchall()
        }

    assert [tuple(row) for row in modes] == [
        ("read-run", "ask"),
        ("write-run", "bypass"),
    ]
    assert tuple(route) == ("write-run", workspace.id, "github", "account", "external")
    assert "conversation_grant_revision" not in route_columns


async def test_migration_23_removes_legacy_conversation_grants_from_bindings(
    tmp_path: Path,
) -> None:
    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 22)
    database = Database(path)
    workspace = Workspace.new(
        name="Legacy connector grant",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await WorkspaceRepository(database).create(workspace)
    now = datetime.now(UTC)
    account = ConnectorAccount.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GITHUB,
        external_account_id="ca_legacy",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now,
    ).activate(now=now)
    binding = ConnectorBinding.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GITHUB,
        account_id=account.id,
        now=now,
    )
    repository = ConnectorRepository(database)
    await repository.save_account(account)
    legacy_config = binding.model_dump(mode="json") | {
        "conversation_access": "read",
        "conversation_tool_ids": ["composio.github.search_commits"],
        "conversation_grant_revision": 4,
    }
    async with aiosqlite.connect(path) as connection:
        await connection.execute(
            """
            INSERT INTO connector_bindings(
                workspace_id, connector, account_id, enabled, auto_fetch_enabled,
                next_sync_at, config, version, created_at, updated_at
            ) VALUES (?, ?, ?, 1, 1, ?, ?, 0, ?, ?)
            """,
            (
                workspace.id,
                ConnectorKind.GITHUB.value,
                account.id,
                binding.next_sync_at.isoformat(),
                json.dumps(legacy_config),
                binding.created_at.isoformat(),
                binding.updated_at.isoformat(),
            ),
        )
        await connection.commit()

    await database.initialize()

    async with database.connect() as connection:
        row = await (
            await connection.execute(
                "SELECT config FROM connector_bindings WHERE workspace_id = ? AND connector = ?",
                (workspace.id, ConnectorKind.GITHUB.value),
            )
        ).fetchone()

    migrated = json.loads(str(row["config"]))
    assert "conversation_access" not in migrated
    assert "conversation_tool_ids" not in migrated
    assert "conversation_grant_revision" not in migrated
    ConnectorBinding.model_validate(migrated)
    replacement = binding.model_copy(update={"version": 1})
    await repository.save_binding(replacement)
    assert await repository.get_binding(workspace.id, ConnectorKind.GITHUB) == replacement


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
