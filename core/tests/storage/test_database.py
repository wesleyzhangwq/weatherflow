import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from weatherflow.activity import ActivityStatistics, ActivitySummaryRevision
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
                "'activity_source_state', 'activity_category_rule_versions', "
                "'activity_summary_tasks', 'activity_summary_attempts', "
                "'activity_summary_revisions', 'activity_summary_dependencies', "
                "'activity_summary_settings', "
                "'activity_statistics', 'activity_evidence_refs', "
                "'privacy_compaction_requests') "
                "ORDER BY name"
            )
        ).fetchall()

    assert journal_mode == ("wal",)
    assert migration == (43,)
    assert tables == [
        ("actions",),
        ("activity_category_rule_versions",),
        ("activity_evidence_refs",),
        ("activity_source_state",),
        ("activity_statistics",),
        ("activity_summary_attempts",),
        ("activity_summary_dependencies",),
        ("activity_summary_revisions",),
        ("activity_summary_settings",),
        ("activity_summary_tasks",),
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
        ("privacy_compaction_requests",),
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

    assert tuple(count) == (43,)


async def test_upgrade_requeues_only_latest_transient_model_fallback_revisions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 41)
    category_id = "c" * 64
    updated_at = "2026-07-19T00:00:00+00:00"
    cases = {
        "auth": ("activity_model_authentication_failed",),
        "temporary": ("activity_model_temporarily_unavailable",),
        "connection": ("activity_model_connection_failed",),
        "route": ("activity_model_route_unavailable",),
        "coverage": ("activity_coverage_none",),
        "output": ("activity_model_output_rejected",),
        "response": ("activity_model_invalid_response",),
        "recovered": ("activity_model_authentication_failed", None),
    }
    async with aiosqlite.connect(path) as connection:
        await connection.execute(
            """
            INSERT INTO activity_category_rule_versions(
                id, canonical_json, rule_count, created_at
            ) VALUES (?, '[]', 0, ?)
            """,
            (category_id, updated_at),
        )
        for index, (name, fallback_reasons) in enumerate(cases.items(), start=1):
            task_id = f"transient-upgrade-{name}"
            window_start = f"2026-07-{index:02d}T00:00:00+00:00"
            window_end = f"2026-07-{index:02d}T06:00:00+00:00"
            current_revision = len(fallback_reasons)
            await connection.execute(
                """
                INSERT INTO activity_summary_tasks(
                    id, task_type, window_start, window_end, timezone,
                    boundary_policy_version, status, finality, attempt_count,
                    not_before, next_retry_at, lease_owner, lease_expires_at,
                    current_revision, category_rule_version, source_watermark,
                    config, created_at, updated_at
                ) VALUES (?, 'stage_6h', ?, ?, 'Asia/Shanghai',
                    'activity-window-boundaries-v1', 'completed', 'final', 1,
                    ?, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    window_start,
                    window_end,
                    window_end,
                    current_revision,
                    category_id,
                    "s" * 64,
                    json.dumps(
                        {
                            "id": task_id,
                            "status": "completed",
                            "finality": "final",
                            "current_revision": current_revision,
                            "completed_at": updated_at,
                            "error_code": None,
                            "updated_at": updated_at,
                        }
                    ),
                    updated_at,
                    updated_at,
                ),
            )
            for revision_number, fallback_reason in enumerate(fallback_reasons, start=1):
                await connection.execute(
                    """
                    INSERT INTO activity_summary_revisions(
                        id, task_id, revision_number, finality,
                        source_watermark, category_rule_version, revision_key,
                        config, completed_at
                    ) VALUES (?, ?, ?, 'final', ?, ?, ?, ?, ?)
                    """,
                    (
                        f"revision-{name}-{revision_number}",
                        task_id,
                        revision_number,
                        "s" * 64,
                        category_id,
                        f"{index:02d}{revision_number:02d}".ljust(64, "r"),
                        json.dumps(
                            {
                                "provider": "local" if fallback_reason else "minimax",
                                "requested_provider": "minimax",
                                "fallback_reason": fallback_reason,
                            }
                        ),
                        updated_at,
                    ),
                )
        await connection.commit()

    database = Database(path)
    await database.initialize()
    await database.initialize()

    async with aiosqlite.connect(path) as connection:
        rows = await (
            await connection.execute(
                """
                SELECT id, status, next_retry_at, current_revision, config
                FROM activity_summary_tasks
                WHERE id LIKE 'transient-upgrade-%'
                ORDER BY id
                """
            )
        ).fetchall()
        revision_count = await (
            await connection.execute(
                """
                SELECT COUNT(*) FROM activity_summary_revisions
                WHERE task_id LIKE 'transient-upgrade-%'
                """
            )
        ).fetchone()

    by_name = {str(row[0]).removeprefix("transient-upgrade-"): row for row in rows}
    for name in ("auth", "temporary", "connection"):
        row = by_name[name]
        config = json.loads(str(row[4]))
        assert row[1] == "needs_retry"
        assert row[2] is not None
        assert config["status"] == "needs_retry"
        assert config["completed_at"] is None
        assert config["error_code"] is None
        assert config["regeneration_reason"] == "transient_model_fallback_recovery_v1"
    for name in ("route", "coverage", "output", "response", "recovered"):
        row = by_name[name]
        assert row[1] == "completed"
        assert row[2] is None
    assert by_name["recovered"][3] == 2
    assert tuple(revision_count) == (9,)


async def test_migration_37_normalizes_legacy_connector_intervals_to_daily(
    tmp_path: Path,
) -> None:
    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 36)
    database = Database(path)
    workspace = Workspace.new(
        name="Legacy connector cadence",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await WorkspaceRepository(database).create(workspace)
    repository = ConnectorRepository(database)
    now = datetime(2026, 7, 18, 0, tzinfo=UTC)
    account = ConnectorAccount.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GMAIL,
        external_account_id="ca_gmail",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now,
    ).activate(now=now)
    await repository.save_account(account)
    binding = ConnectorBinding.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GMAIL,
        account_id=account.id,
        now=now,
    )
    legacy_config = binding.model_dump(mode="json")
    legacy_config["interval_minutes"] = 60
    legacy_next_sync = "2099-01-01T00:00:00+00:00"
    legacy_config["next_sync_at"] = legacy_next_sync
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
                ConnectorKind.GMAIL.value,
                account.id,
                legacy_next_sync,
                json.dumps(legacy_config),
                binding.created_at.isoformat(),
                binding.updated_at.isoformat(),
            ),
        )
        await connection.commit()

    migration_started_at = datetime.now(UTC)
    await database.initialize()
    migration_finished_at = datetime.now(UTC)

    migrated = await repository.get_binding(workspace.id, ConnectorKind.GMAIL)
    assert migrated is not None
    assert migrated.interval_minutes == 1_440
    assert migrated.fetch_contract_version == "connector-fetch-v2-daily-source-specific"
    assert migration_started_at <= migrated.next_sync_at <= migration_finished_at
    assert migrated.version == binding.version + 1
    async with database.connect() as connection:
        row = await (
            await connection.execute(
                """
                SELECT next_sync_at FROM connector_bindings
                WHERE workspace_id = ? AND connector = ?
                """,
                (workspace.id, ConnectorKind.GMAIL.value),
            )
        ).fetchone()
    assert row is not None
    stored_next_sync = datetime.fromisoformat(str(row["next_sync_at"]).replace("Z", "+00:00"))
    assert stored_next_sync == migrated.next_sync_at


async def test_migration_39_repairs_already_applied_legacy_connector_migration(
    tmp_path: Path,
) -> None:
    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 38)
    database = Database(path)
    workspace = Workspace.new(
        name="Legacy connector strategy",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await WorkspaceRepository(database).create(workspace)
    repository = ConnectorRepository(database)
    now = datetime(2026, 7, 18, 0, tzinfo=UTC)
    account = ConnectorAccount.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GITHUB,
        external_account_id="ca_github",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now,
    ).activate(now=now)
    await repository.save_account(account)
    binding = ConnectorBinding.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GITHUB,
        account_id=account.id,
        now=now,
    )
    legacy_next_sync = "2099-01-01T00:00:00+00:00"
    legacy_config = binding.model_dump(mode="json")
    legacy_config.pop("fetch_contract_version")
    legacy_config["next_sync_at"] = legacy_next_sync
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
                legacy_next_sync,
                json.dumps(legacy_config),
                binding.created_at.isoformat(),
                binding.updated_at.isoformat(),
            ),
        )
        await connection.commit()

    migration_started_at = datetime.now(UTC)
    await database.initialize()
    migration_finished_at = datetime.now(UTC)

    migrated = await repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert migrated is not None
    assert migrated.interval_minutes == 1_440
    assert migrated.fetch_contract_version == "connector-fetch-v2-daily-source-specific"
    assert migration_started_at <= migrated.next_sync_at <= migration_finished_at
    assert migrated.version == binding.version + 1


async def test_migration_33_removes_persisted_activity_application_and_domain_labels(
    tmp_path: Path,
) -> None:
    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 32)
    started_at = datetime(2026, 7, 16, 0, tzinfo=UTC)
    completed_at = datetime(2026, 7, 16, 7, tzinfo=UTC)
    statistics = ActivityStatistics(
        window_start=started_at,
        window_end=started_at.replace(hour=6),
        active_seconds=3_600,
        application_seconds={"PRIVATE_APP_LABEL_SENTINEL": 3_600},
        category_seconds={"Work / Development": 3_600},
        domain_seconds={"PRIVATE_DOMAIN_LABEL_SENTINEL.test": 1_800},
        source_watermark="w" * 64,
    )
    revision = ActivitySummaryRevision(
        id="revision-legacy-labels",
        task_id="task-legacy-labels",
        revision_number=1,
        finality="final",
        statistics=statistics,
        summary_text=(
            "PRIVATE_APP_LABEL_SENTINEL and PRIVATE_DOMAIN_LABEL_SENTINEL.test were prominent."
        ),
        evidence_refs=(),
        category_rule_version="c" * 64,
        category_rules_json="[]",
        provider="local",
        model="deterministic-activity-v1",
        prompt_version="activity-summary-prompt-v2:test",
        statistics_version=statistics.statistics_version,
        request_digest="r" * 64,
        source_watermark=statistics.source_watermark,
        completed_at=completed_at,
    )
    task_config = {
        "id": revision.task_id,
        "task_type": "stage_6h",
        "window_start": statistics.window_start.isoformat(),
        "window_end": statistics.window_end.isoformat(),
        "timezone": "Asia/Shanghai",
        "boundary_policy_version": "activity-window-boundaries-v1",
        "status": "completed",
        "attempt_count": 1,
        "not_before": completed_at.isoformat(),
        "finality": "final",
        "completed_at": completed_at.isoformat(),
        "category_rule_version": revision.category_rule_version,
        "provider": revision.provider,
        "model": revision.model,
        "prompt_version": revision.prompt_version,
        "statistics_version": revision.statistics_version,
        "current_revision": 1,
        "source_watermark": revision.source_watermark,
        "created_at": completed_at.isoformat(),
        "updated_at": completed_at.isoformat(),
    }
    async with aiosqlite.connect(path) as connection:
        await connection.execute(
            """
            INSERT INTO activity_category_rule_versions(
                id, canonical_json, rule_count, created_at
            ) VALUES (?, '[]', 0, ?)
            """,
            (revision.category_rule_version, completed_at.isoformat()),
        )
        await connection.execute(
            """
            INSERT INTO activity_summary_tasks(
                id, task_type, window_start, window_end, timezone,
                boundary_policy_version, status, finality, attempt_count,
                not_before, current_revision, category_rule_version,
                source_watermark, config, created_at, updated_at
            ) VALUES (?, 'stage_6h', ?, ?, 'Asia/Shanghai', ?, 'completed',
                      'final', 1, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                revision.task_id,
                statistics.window_start.isoformat(),
                statistics.window_end.isoformat(),
                "activity-window-boundaries-v1",
                completed_at.isoformat(),
                revision.category_rule_version,
                revision.source_watermark,
                json.dumps(task_config),
                completed_at.isoformat(),
                completed_at.isoformat(),
            ),
        )
        await connection.execute(
            """
            INSERT INTO activity_summary_revisions(
                id, task_id, revision_number, finality, source_watermark,
                category_rule_version, revision_key, config, completed_at
            ) VALUES (?, ?, 1, 'final', ?, ?, 'legacy-label-key', ?, ?)
            """,
            (
                revision.id,
                revision.task_id,
                revision.source_watermark,
                revision.category_rule_version,
                revision.model_dump_json(),
                revision.completed_at.isoformat(),
            ),
        )
        await connection.execute(
            "INSERT INTO activity_statistics(revision_id, config) VALUES (?, ?)",
            (revision.id, statistics.model_dump_json()),
        )
        await connection.commit()

    await Database(path).initialize()

    async with aiosqlite.connect(path) as connection:
        connection.row_factory = aiosqlite.Row
        revision_row = await (
            await connection.execute(
                "SELECT config FROM activity_summary_revisions WHERE id = ?",
                (revision.id,),
            )
        ).fetchone()
        statistics_row = await (
            await connection.execute(
                "SELECT config FROM activity_statistics WHERE revision_id = ?",
                (revision.id,),
            )
        ).fetchone()

    assert revision_row is not None and statistics_row is not None
    stored_revision = ActivitySummaryRevision.model_validate_json(revision_row["config"])
    stored_statistics = ActivityStatistics.model_validate_json(statistics_row["config"])
    assert stored_revision.statistics.application_seconds == {}
    assert stored_revision.statistics.domain_seconds == {}
    assert stored_revision.statistics.category_seconds == {"Work / Development": 3_600}
    assert stored_statistics.application_seconds == {}
    assert stored_statistics.domain_seconds == {}
    assert stored_statistics.category_seconds == {"Work / Development": 3_600}
    durable = f"{revision_row['config']} {statistics_row['config']}"
    assert "PRIVATE_APP_LABEL_SENTINEL" not in durable
    assert "PRIVATE_DOMAIN_LABEL_SENTINEL" not in durable
    physical_bytes = path.read_bytes()
    wal_path = path.with_name(f"{path.name}-wal")
    if wal_path.exists():
        physical_bytes += wal_path.read_bytes()
    assert b"PRIVATE_APP_LABEL_SENTINEL" not in physical_bytes
    assert b"PRIVATE_DOMAIN_LABEL_SENTINEL" not in physical_bytes


async def test_migration_27_replaces_raw_activity_vault_with_derived_ledger(
    tmp_path: Path,
) -> None:
    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 26)
    async with aiosqlite.connect(path) as connection:
        await connection.execute(
            """
            INSERT INTO activity_events(
                id, source, device_id, source_instance, source_event_id,
                started_at, ended_at, observed_at, duration_seconds,
                app_name, bundle_id, window_title, idle_state, state_hash,
                created_at, updated_at
            ) VALUES (
                'legacy-event', 'macos_window', 'macbook', 'native-main', 'window-1',
                '2026-07-16T06:00:00+00:00', '2026-07-16T06:00:10+00:00',
                '2026-07-16T06:00:10+00:00', 10,
                'Terminal', 'com.apple.Terminal', 'LEGACY_ACTIVITY_RAW_SENTINEL',
                'active', 'hash',
                '2026-07-16T06:00:00+00:00', '2026-07-16T06:00:10+00:00'
            )
            """
        )
        await connection.commit()

    await Database(path).initialize()

    async with aiosqlite.connect(path) as connection:
        tables = {
            str(row[0])
            for row in await (
                await connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).fetchall()
        }
        derived_sql = "\n".join(
            str(row[0])
            for row in await (
                await connection.execute(
                    """
                    SELECT sql
                    FROM sqlite_master
                    WHERE type = 'table' AND name LIKE 'activity_%'
                    ORDER BY name
                    """
                )
            ).fetchall()
        )

    assert {
        "activity_preferences",
        "activity_events",
        "activity_heartbeat_receipts",
        "activity_inference_jobs",
    }.isdisjoint(tables)
    assert {
        "activity_source_state",
        "activity_category_rule_versions",
        "activity_summary_tasks",
        "activity_summary_attempts",
        "activity_summary_revisions",
        "activity_summary_dependencies",
        "activity_statistics",
        "activity_evidence_refs",
    }.issubset(tables)
    assert {
        "activity_state_inferences",
        "activity_live_inferences",
        "activity_live_evidence_refs",
        "activity_live_state_assessments",
    }.isdisjoint(tables)
    assert "window_title" not in derived_sql
    assert "url" not in derived_sql
    physical_bytes = path.read_bytes()
    wal_path = path.with_name(f"{path.name}-wal")
    if wal_path.exists():
        physical_bytes += wal_path.read_bytes()
    assert b"LEGACY_ACTIVITY_RAW_SENTINEL" not in physical_bytes


async def test_secure_compact_removes_deleted_content_from_database_and_wal(
    tmp_path: Path,
) -> None:
    path = tmp_path / "weatherflow.db"
    database = Database(path)
    await database.initialize()
    sentinel = "ACTIVITY_RESET_PHYSICAL_SENTINEL_" + ("x" * 8_192)
    now = datetime.now(UTC).isoformat()
    async with database.transaction() as connection:
        await connection.execute(
            """
            INSERT INTO events(
                id, type, recorded_at, actor, stream_kind, stream_id,
                correlation_id, causation_id, payload, sensitivity,
                retention_class
            ) VALUES (
                'activity-reset-sentinel', 'run.result_committed', ?,
                'agent', 'run', 'activity-run', 'activity-run', NULL,
                ?, 'normal', 'audit'
            )
            """,
            (now, json.dumps({"summary": sentinel})),
        )
    async with database.transaction() as connection:
        await connection.execute("DELETE FROM events WHERE id = 'activity-reset-sentinel'")

    await database.secure_compact()

    physical_bytes = path.read_bytes()
    wal_path = path.with_name(f"{path.name}-wal")
    if wal_path.exists():
        physical_bytes += wal_path.read_bytes()
    assert sentinel.encode() not in physical_bytes


async def test_migration_28_adds_bounded_live_inference_storage(tmp_path: Path) -> None:
    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 28)

    now = datetime.now(UTC).isoformat()
    async with aiosqlite.connect(path) as connection:
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute(
            """
            INSERT INTO activity_live_inferences(
                id, label, confidence, valid_from, valid_until,
                source_watermark, config, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "live-inference",
                "focus",
                0.8,
                "2026-07-16T06:00:00+00:00",
                "2026-07-16T06:05:00+00:00",
                "a" * 64,
                '{"label":"focus","evidence_refs":[]}',
                now,
            ),
        )
        await connection.execute(
            """
            INSERT INTO activity_live_evidence_refs(
                inference_id, ordinal, bucket_id, event_id,
                event_timestamp, event_digest, config
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "live-inference",
                0,
                "aw-watcher-window_local",
                "event-1",
                "2026-07-16T06:00:00+00:00",
                "b" * 64,
                '{"fields_used":["application"]}',
            ),
        )
        await connection.commit()
        live_sql = "\n".join(
            str(row[0])
            for row in await (
                await connection.execute(
                    """
                    SELECT sql
                    FROM sqlite_master
                    WHERE type = 'table' AND name LIKE 'activity_live_%'
                    ORDER BY name
                    """
                )
            ).fetchall()
        )
        await connection.execute("DELETE FROM activity_live_inferences WHERE id = 'live-inference'")
        evidence_count = await (
            await connection.execute("SELECT COUNT(*) FROM activity_live_evidence_refs")
        ).fetchone()

    assert "window_title" not in live_sql
    assert "url" not in live_sql
    assert tuple(evidence_count) == (0,)


async def test_migration_35_removes_activity_state_inference_storage(tmp_path: Path) -> None:
    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 34)
    sentinel = "REMOVED_ACTIVITY_STATE_INFERENCE_SENTINEL_" + ("x" * 8_192)
    checked_at = "2026-07-18T00:00:00+00:00"
    async with aiosqlite.connect(path) as connection:
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute(
            """
            INSERT INTO activity_source_state(singleton_id, health, config, updated_at)
            VALUES (1, 'available', ?, ?)
            """,
            (
                json.dumps(
                    {
                        "health": "available",
                        "checked_at": checked_at,
                        "last_live_inference_checked_at": checked_at,
                    }
                ),
                checked_at,
            ),
        )
        await connection.execute(
            """
            INSERT INTO activity_evidence_refs(
                owner_type, owner_id, ordinal, bucket_id, event_id,
                event_timestamp, event_digest, config
            ) VALUES
                ('revision', 'revision-1', 0, 'window', 'event-1', ?, ?, '{}'),
                ('inference', 'inference-1', 0, 'window', 'event-2', ?, ?, '{}')
            """,
            (checked_at, "a" * 64, checked_at, "b" * 64),
        )
        await connection.execute(
            """
            INSERT INTO activity_live_inferences(
                id, label, confidence, valid_from, valid_until,
                source_watermark, config, created_at
            ) VALUES (?, 'focus', 0.8, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-live-inference",
                checked_at,
                "2026-07-18T00:15:00+00:00",
                "c" * 64,
                json.dumps({"sentinel": sentinel}),
                checked_at,
            ),
        )
        await connection.commit()

    await Database(path).initialize()

    async with aiosqlite.connect(path) as connection:
        tables = {
            str(row[0])
            for row in await (
                await connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).fetchall()
        }
        evidence = await (
            await connection.execute(
                "SELECT owner_type, owner_id FROM activity_evidence_refs ORDER BY owner_id"
            )
        ).fetchall()
        evidence_schema = await (
            await connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'activity_evidence_refs'"
            )
        ).fetchone()
        source_state = await (
            await connection.execute(
                "SELECT config FROM activity_source_state WHERE singleton_id = 1"
            )
        ).fetchone()
        compaction = await (
            await connection.execute("SELECT COUNT(*) FROM privacy_compaction_requests")
        ).fetchone()

    assert {
        "activity_live_state_assessments",
        "activity_live_evidence_refs",
        "activity_live_inferences",
        "activity_state_inferences",
    }.isdisjoint(tables)
    assert evidence == [("revision", "revision-1")]
    assert "owner_type = 'revision'" in str(evidence_schema[0])
    assert "last_live_inference_checked_at" not in json.loads(str(source_state[0]))
    assert tuple(compaction) == (0,)
    physical_bytes = path.read_bytes()
    wal_path = path.with_name(f"{path.name}-wal")
    if wal_path.exists():
        physical_bytes += wal_path.read_bytes()
    assert sentinel.encode() not in physical_bytes


async def test_prompt_migrations_remove_custom_prompt_and_select_current_contract(
    tmp_path: Path,
) -> None:
    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 35)
    sentinel = "CUSTOM_SUMMARY_PROMPT_SENTINEL_" + ("x" * 8_192)
    unsafe_summary = "OLD_UNSAFE_ACTIVITY_SUMMARY_CHROME_路线图_专注状态"
    updated_at = "2026-07-18T00:00:00+00:00"
    async with aiosqlite.connect(path) as connection:
        await connection.execute(
            """
            INSERT INTO activity_summary_settings(singleton_id, version, config, updated_at)
            VALUES (1, 4, ?, ?)
            """,
            (
                json.dumps(
                    {
                        "version": 4,
                        "prompt": sentinel,
                        "prompt_version": "activity-summary-prompt-v2:user",
                        "updated_at": updated_at,
                    }
                ),
                updated_at,
            ),
        )
        await connection.execute(
            """
            INSERT INTO activity_summary_tasks(
                id, task_type, window_start, window_end, timezone,
                boundary_policy_version, status, finality, attempt_count,
                not_before, next_retry_at, lease_owner, lease_expires_at,
                current_revision, category_rule_version, source_watermark,
                config, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-summary-task",
                "stage_6h",
                "2026-07-17T16:00:00+00:00",
                "2026-07-17T22:00:00+00:00",
                "Asia/Shanghai",
                "activity-window-boundaries-v1",
                "completed",
                "final",
                1,
                "2026-07-17T23:00:00+00:00",
                None,
                None,
                None,
                1,
                None,
                None,
                json.dumps(
                    {
                        "status": "completed",
                        "completed_at": updated_at,
                        "error_code": None,
                        "prompt_version": "activity-summary-prompt-v2:user",
                        "updated_at": updated_at,
                    }
                ),
                updated_at,
                updated_at,
            ),
        )
        await connection.execute(
            """
            INSERT INTO activity_summary_revisions(
                id, task_id, revision_number, finality, source_watermark,
                category_rule_version, revision_key, config, completed_at
            ) VALUES (?, ?, 1, 'final', ?, ?, ?, ?, ?)
            """,
            (
                "legacy-unsafe-revision",
                "legacy-summary-task",
                "s" * 64,
                "c" * 64,
                "r" * 64,
                json.dumps(
                    {
                        "summary_text": unsafe_summary,
                        "prompt_version": "activity-summary-prompt-v4-context-sequence-zh-fixed",
                    },
                    ensure_ascii=False,
                ),
                updated_at,
            ),
        )
        await connection.commit()

    await Database(path).initialize()

    async with aiosqlite.connect(path) as connection:
        row = await (
            await connection.execute(
                "SELECT version, config FROM activity_summary_settings WHERE singleton_id = 1"
            )
        ).fetchone()
        compaction = await (
            await connection.execute("SELECT COUNT(*) FROM privacy_compaction_requests")
        ).fetchone()
        task_row = await (
            await connection.execute(
                "SELECT status, next_retry_at, config FROM activity_summary_tasks WHERE id = ?",
                ("legacy-summary-task",),
            )
        ).fetchone()
        revision_row = await (
            await connection.execute(
                "SELECT config FROM activity_summary_revisions WHERE id = ?",
                ("legacy-unsafe-revision",),
            )
        ).fetchone()

    assert row is not None
    config = json.loads(str(row[1]))
    assert int(row[0]) == 7
    assert config["version"] == 7
    assert "prompt" not in config
    assert config["prompt_version"].startswith(
        "activity-summary-prompt-v5-privacy-context-sequence-zh-fixed:"
    )
    assert task_row is not None
    task_config = json.loads(str(task_row[2]))
    assert task_row[0] == "needs_retry"
    assert task_row[1] is not None
    assert task_config["status"] == "needs_retry"
    assert task_config["completed_at"] is None
    assert task_config["error_code"] is None
    assert task_config["regeneration_reason"] == "privacy_context_sequence_prompt_v5"
    assert revision_row is not None
    revision_config = json.loads(str(revision_row[0]))
    assert revision_config["summary_text"].startswith("该历史总结使用旧版隐私合同生成")
    assert unsafe_summary not in revision_config["summary_text"]
    assert tuple(compaction) == (0,)
    physical_bytes = path.read_bytes()
    wal_path = path.with_name(f"{path.name}-wal")
    if wal_path.exists():
        physical_bytes += wal_path.read_bytes()
    assert sentinel.encode() not in physical_bytes
    assert unsafe_summary.encode() not in physical_bytes


async def test_migration_29_removes_legacy_activity_rhythm_derivations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 28)
    now = datetime.now(UTC).isoformat()
    async with aiosqlite.connect(path) as connection:
        await connection.execute("PRAGMA foreign_keys = ON")
        for workspace_id in ("workspace-affected", "workspace-unrelated"):
            await connection.execute(
                """
                INSERT INTO workspaces(
                    id, name, config, version, created_at, updated_at
                ) VALUES (?, ?, '{}', 0, ?, ?)
                """,
                (workspace_id, workspace_id, now, now),
            )
        events = (
            (
                "legacy-activity",
                "rhythm.signal.activity_metadata",
                "workspace",
                "workspace-affected",
                "workspace-affected",
                {
                    "signal": {
                        "kind": "activity_metadata",
                        "window_title": "legacy raw title",
                    }
                },
            ),
            (
                "unrelated-signal",
                "rhythm.signal.checkin",
                "workspace",
                "workspace-unrelated",
                "workspace-unrelated",
                {"signal": {"kind": "checkin", "text": "steady", "observed_at": now}},
            ),
            (
                "derived-affected",
                "rhythm.snapshot_derived",
                "rhythm_snapshot",
                "historical-affected",
                "workspace-affected",
                {"supporting_event_ids": ["legacy-activity"]},
            ),
            (
                "remote-affected",
                "rhythm.snapshot_remote_inference",
                "rhythm_snapshot",
                "remote-affected",
                "workspace-affected",
                {"evidence_event_ids": ["legacy-activity"]},
            ),
            (
                "derived-unrelated",
                "rhythm.snapshot_derived",
                "rhythm_snapshot",
                "current-unrelated",
                "workspace-unrelated",
                {"supporting_event_ids": ["unrelated-signal"]},
            ),
            (
                "memory-episode-affected",
                "memory.episode_created",
                "episodic_memory",
                "episode-affected",
                "workspace-affected",
                {"source_event_ids": ["legacy-activity"]},
            ),
            (
                "memory-profile-affected",
                "memory.profile_assertion_created",
                "profile_assertion",
                "profile-affected",
                "workspace-affected",
                {"evidence_event_ids": ["legacy-activity"]},
            ),
        )
        for event_id, event_type, stream_kind, stream_id, correlation_id, payload in events:
            await connection.execute(
                """
                INSERT INTO events(
                    id, type, recorded_at, actor, stream_kind, stream_id,
                    correlation_id, causation_id, payload, sensitivity,
                    retention_class
                ) VALUES (?, ?, ?, 'system', ?, ?, ?, NULL, ?, 'normal', 'audit')
                """,
                (
                    event_id,
                    event_type,
                    now,
                    stream_kind,
                    stream_id,
                    correlation_id,
                    json.dumps(payload),
                ),
            )
        await connection.execute(
            """
            INSERT INTO rhythm_snapshots(workspace_id, snapshot, version, updated_at)
            VALUES
                ('workspace-affected', ?, 0, ?),
                ('workspace-unrelated', ?, 0, ?)
            """,
            (
                json.dumps({"id": "current-affected"}),
                now,
                json.dumps({"id": "current-unrelated"}),
                now,
            ),
        )
        for run_id, workspace_id, snapshot_id in (
            ("run-current", "workspace-affected", "current-affected"),
            ("run-historical", "workspace-affected", "historical-affected"),
            ("run-remote", "workspace-affected", "remote-affected"),
            ("run-unrelated", "workspace-unrelated", "current-unrelated"),
        ):
            await connection.execute(
                """
                INSERT INTO runs(
                    id, client_request_id, user_intent, workspace_id, status,
                    version, created_at, updated_at, rhythm_snapshot_id,
                    policy_profile, budget
                ) VALUES (?, ?, 'test', ?, 'queued', 0, ?, ?, ?, 'supervised', '{}')
                """,
                (
                    run_id,
                    f"request-{run_id}",
                    workspace_id,
                    now,
                    now,
                    snapshot_id,
                ),
            )
        await connection.execute(
            """
            INSERT INTO episodic_memories(
                id, workspace_id, summary, source_event_ids, tags, created_at
            ) VALUES
                ('episode-affected', 'workspace-affected', 'legacy', ?, '[]', ?),
                ('episode-unrelated', 'workspace-unrelated', 'steady', ?, '[]', ?)
            """,
            (
                json.dumps(["legacy-activity"]),
                now,
                json.dumps(["unrelated-signal"]),
                now,
            ),
        )
        await connection.execute(
            """
            INSERT INTO profile_assertions(
                id, workspace_id, claim, confidence, status,
                evidence_event_ids, origin, version, created_at,
                last_confirmed_at, updated_at
            ) VALUES
                (
                    'profile-affected', 'workspace-affected', 'legacy', 0.8,
                    'active', ?, 'derived', 0, ?, ?, ?
                ),
                (
                    'profile-unrelated', 'workspace-unrelated', 'steady', 0.8,
                    'active', ?, 'derived', 0, ?, ?, ?
                )
            """,
            (
                json.dumps(["legacy-activity"]),
                now,
                now,
                now,
                json.dumps(["unrelated-signal"]),
                now,
                now,
                now,
            ),
        )
        for workspace_id, kind, entry_id in (
            ("workspace-affected", "episode", "episode-affected"),
            ("workspace-unrelated", "episode", "episode-unrelated"),
            ("workspace-affected", "profile_assertion", "profile-affected"),
            ("workspace-unrelated", "profile_assertion", "profile-unrelated"),
        ):
            await connection.execute(
                """
                INSERT INTO memory_search_index(
                    workspace_id, entry_kind, entry_id, terms, updated_at
                ) VALUES (?, ?, ?, '[]', ?)
                """,
                (workspace_id, kind, entry_id, now),
            )
        await connection.commit()

    await Database(path).initialize()

    async with aiosqlite.connect(path) as connection:
        event_ids = {
            str(row[0])
            for row in await (await connection.execute("SELECT id FROM events")).fetchall()
        }
        snapshots = {
            str(row[0])
            for row in await (
                await connection.execute("SELECT workspace_id FROM rhythm_snapshots")
            ).fetchall()
        }
        run_refs = {
            str(row[0]): row[1]
            for row in await (
                await connection.execute("SELECT id, rhythm_snapshot_id FROM runs ORDER BY id")
            ).fetchall()
        }
        episodes = {
            str(row[0])
            for row in await (
                await connection.execute("SELECT id FROM episodic_memories")
            ).fetchall()
        }
        profiles = {
            str(row[0])
            for row in await (
                await connection.execute("SELECT id FROM profile_assertions")
            ).fetchall()
        }
        index_entries = {
            (str(row[0]), str(row[1]))
            for row in await (
                await connection.execute("SELECT entry_kind, entry_id FROM memory_search_index")
            ).fetchall()
        }

    assert {
        "legacy-activity",
        "derived-affected",
        "remote-affected",
        "memory-episode-affected",
        "memory-profile-affected",
    }.isdisjoint(event_ids)
    assert {"unrelated-signal", "derived-unrelated"}.issubset(event_ids)
    assert snapshots == {"workspace-unrelated"}
    assert run_refs == {
        "run-current": None,
        "run-historical": None,
        "run-remote": None,
        "run-unrelated": "current-unrelated",
    }
    assert episodes == {"episode-unrelated"}
    assert profiles == {"profile-unrelated"}
    assert index_entries == {
        ("episode", "episode-unrelated"),
        ("profile_assertion", "profile-unrelated"),
    }


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


async def test_latest_migration_repairs_bindings_written_by_an_older_v23(
    tmp_path: Path,
) -> None:
    """Installed databases may have applied v23 before its cleanup SQL existed."""

    path = tmp_path / "weatherflow.db"
    await initialize_through(path, 30)
    database = Database(path)
    workspace = Workspace.new(
        name="Previously migrated connector",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await WorkspaceRepository(database).create(workspace)
    now = datetime.now(UTC)
    account = ConnectorAccount.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GITHUB,
        external_account_id="ca_previously_migrated",
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
    await repository.save_binding(binding)
    legacy_config = binding.model_dump(mode="json") | {
        "conversation_access": "disabled",
        "conversation_tool_ids": [],
        "conversation_grant_revision": 0,
    }
    async with aiosqlite.connect(path) as connection:
        await connection.execute(
            "UPDATE connector_bindings SET config = ? WHERE workspace_id = ? AND connector = ?",
            (json.dumps(legacy_config), workspace.id, ConnectorKind.GITHUB.value),
        )
        await connection.commit()

    await database.initialize()

    repaired = await repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert repaired is not None
    repaired_stable = repaired.model_dump(exclude={"next_sync_at", "version", "updated_at"})
    binding_stable = binding.model_dump(exclude={"next_sync_at", "version", "updated_at"})
    assert repaired_stable == binding_stable
    assert repaired.next_sync_at >= binding.next_sync_at
    assert repaired.version == binding.version + 1
    assert await repository.list_bindings(workspace.id) == [repaired]
    async with database.connect() as connection:
        row = await (
            await connection.execute(
                "SELECT config FROM connector_bindings WHERE workspace_id = ? AND connector = ?",
                (workspace.id, ConnectorKind.GITHUB.value),
            )
        ).fetchone()
    stored = json.loads(str(row["config"]))
    assert "conversation_access" not in stored
    assert "conversation_tool_ids" not in stored
    assert "conversation_grant_revision" not in stored


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
