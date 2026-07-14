from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    sql: str


MIGRATIONS = (
    Migration(
        version=1,
        sql="""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            stream_kind TEXT NOT NULL,
            stream_id TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            causation_id TEXT,
            payload TEXT NOT NULL,
            sensitivity TEXT NOT NULL,
            retention_class TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_events_stream
            ON events(stream_kind, stream_id, recorded_at, id);
        CREATE INDEX IF NOT EXISTS idx_events_correlation
            ON events(correlation_id, recorded_at, id);
        """,
    ),
    Migration(
        version=2,
        sql="""
        CREATE TABLE runs (
            id TEXT PRIMARY KEY,
            client_request_id TEXT NOT NULL UNIQUE,
            user_intent TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            status TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            rhythm_snapshot_id TEXT,
            capability_snapshot_id TEXT,
            policy_profile TEXT NOT NULL,
            budget TEXT NOT NULL,
            checkpoint_ref TEXT,
            result_summary TEXT,
            error_class TEXT,
            error_message TEXT
        );
        CREATE INDEX idx_runs_status ON runs(status, updated_at);
        """,
    ),
    Migration(
        version=3,
        sql="""
        CREATE TABLE actions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            tool_id TEXT NOT NULL,
            arguments TEXT NOT NULL,
            effect TEXT NOT NULL,
            status TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            preview TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            version INTEGER NOT NULL,
            result TEXT,
            error_class TEXT,
            error_message TEXT
        );
        CREATE INDEX idx_actions_run_status ON actions(run_id, status, updated_at);

        CREATE TABLE approvals (
            id TEXT PRIMARY KEY,
            action_id TEXT NOT NULL UNIQUE REFERENCES actions(id),
            run_id TEXT NOT NULL REFERENCES runs(id),
            status TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            decided_at TEXT,
            decided_by TEXT,
            rationale TEXT,
            version INTEGER NOT NULL
        );
        CREATE INDEX idx_approvals_run_status ON approvals(run_id, status, requested_at);
        """,
    ),
    Migration(
        version=4,
        sql="""
        CREATE TABLE capability_snapshots (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
            catalog_revision TEXT NOT NULL,
            tools TEXT NOT NULL,
            digest TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_capability_snapshots_run
            ON capability_snapshots(run_id, created_at);
        """,
    ),
    Migration(
        version=5,
        sql="""
        CREATE TABLE artifacts (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            name TEXT NOT NULL,
            media_type TEXT NOT NULL,
            digest TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            relative_path TEXT NOT NULL,
            validation TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_artifacts_run ON artifacts(run_id, created_at, id);
        """,
    ),
    Migration(
        version=6,
        sql="""
        CREATE TABLE checkpoints (
            run_id TEXT PRIMARY KEY REFERENCES runs(id),
            version INTEGER NOT NULL,
            step_index INTEGER NOT NULL,
            transcript TEXT NOT NULL,
            state TEXT NOT NULL,
            pending_action_id TEXT,
            updated_at TEXT NOT NULL
        );
        """,
    ),
    Migration(
        version=7,
        sql="""
        CREATE TABLE workspaces (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            config TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_workspaces_name ON workspaces(name, created_at, id);
        """,
    ),
    Migration(
        version=8,
        sql="""
        CREATE TABLE rhythm_snapshots (
            workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id),
            snapshot TEXT NOT NULL,
            version INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
    Migration(
        version=9,
        sql="""
        CREATE TABLE episodic_memories (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id),
            summary TEXT NOT NULL,
            source_event_ids TEXT NOT NULL,
            tags TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_episodic_memories_workspace
            ON episodic_memories(workspace_id, created_at, id);

        CREATE TABLE profile_assertions (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id),
            claim TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,
            evidence_event_ids TEXT NOT NULL,
            origin TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            last_confirmed_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_profile_assertions_workspace_status
            ON profile_assertions(workspace_id, status, updated_at, id);

        CREATE TABLE memory_search_index (
            workspace_id TEXT NOT NULL REFERENCES workspaces(id),
            entry_kind TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            terms TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(entry_kind, entry_id)
        );
        CREATE INDEX idx_memory_search_index_workspace
            ON memory_search_index(workspace_id, entry_kind, entry_id);
        """,
    ),
    Migration(
        version=10,
        sql="""
        CREATE TABLE checkpoint_quarantine (
            run_id TEXT PRIMARY KEY REFERENCES runs(id),
            reason TEXT NOT NULL,
            raw_payload BLOB NOT NULL,
            payload_sha256 TEXT NOT NULL,
            quarantined_at TEXT NOT NULL
        );
        """,
    ),
    Migration(
        version=11,
        sql="""
        CREATE TABLE onboarding_preferences (
            workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id),
            completed INTEGER NOT NULL,
            metadata_sensor_enabled INTEGER NOT NULL,
            version INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
    Migration(
        version=12,
        sql="""
        CREATE TABLE model_configurations (
            workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id),
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            base_url TEXT NOT NULL,
            credential_ref TEXT NOT NULL,
            version INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
    Migration(
        version=13,
        sql="""
        CREATE TABLE connector_accounts (
            id TEXT PRIMARY KEY,
            connector TEXT NOT NULL UNIQUE,
            external_account_id TEXT NOT NULL UNIQUE,
            phase TEXT NOT NULL,
            config TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE connector_installation (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            user_id TEXT NOT NULL UNIQUE
        );

        CREATE TABLE connection_attempts (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            connector TEXT NOT NULL,
            account_id TEXT NOT NULL REFERENCES connector_accounts(id) ON DELETE CASCADE,
            phase TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            config TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_connection_attempts_connector
            ON connection_attempts(connector, created_at);

        CREATE TABLE connector_bindings (
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            connector TEXT NOT NULL,
            account_id TEXT NOT NULL REFERENCES connector_accounts(id) ON DELETE CASCADE,
            enabled INTEGER NOT NULL,
            auto_fetch_enabled INTEGER NOT NULL,
            next_sync_at TEXT NOT NULL,
            config TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(workspace_id, connector)
        );
        CREATE INDEX idx_connector_bindings_due
            ON connector_bindings(enabled, auto_fetch_enabled, next_sync_at);

        CREATE TABLE connector_snapshots (
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            connector TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            snapshot TEXT NOT NULL,
            PRIMARY KEY(workspace_id, connector)
        );
        """,
    ),
    Migration(
        version=14,
        sql="""
        CREATE TABLE provider_continuations (
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            step_index INTEGER NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            nonce BLOB NOT NULL,
            ciphertext BLOB NOT NULL,
            payload_sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            PRIMARY KEY(run_id, step_index),
            CHECK(step_index > 0),
            CHECK(schema_version = 1),
            CHECK(length(nonce) = 12),
            CHECK(length(payload_sha256) = 64)
        );
        CREATE INDEX idx_provider_continuations_expiry
            ON provider_continuations(expires_at, run_id, step_index);
        """,
    ),
    Migration(
        version=15,
        sql="""
        CREATE TABLE run_model_routes (
            run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            configuration_workspace_id TEXT,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            base_url TEXT,
            credential_ref TEXT,
            configuration_version INTEGER,
            bound_at TEXT NOT NULL,
            CHECK(configuration_version IS NULL OR configuration_version >= 0),
            CHECK(
                (provider = 'echo' AND base_url IS NULL
                    AND credential_ref IS NULL AND configuration_version IS NULL
                    AND configuration_workspace_id IS NULL)
                OR
                (provider != 'echo' AND base_url IS NOT NULL
                    AND credential_ref IS NOT NULL AND configuration_version IS NOT NULL
                    AND configuration_workspace_id IS NOT NULL)
            )
        );
        CREATE INDEX idx_run_model_routes_workspace
            ON run_model_routes(workspace_id, bound_at, run_id);
        """,
    ),
    Migration(
        version=16,
        sql="""
        CREATE TABLE automations (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            next_run_at TEXT,
            config TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_automations_workspace_status
            ON automations(workspace_id, status, updated_at, id);
        CREATE INDEX idx_automations_due
            ON automations(status, next_run_at, id);

        CREATE TABLE automation_run_links (
            id TEXT PRIMARY KEY,
            automation_id TEXT NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            trigger TEXT NOT NULL,
            scheduled_for TEXT NOT NULL,
            client_request_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
            error_code TEXT,
            config TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_automation_run_links_history
            ON automation_run_links(automation_id, created_at DESC, id DESC);
        CREATE INDEX idx_automation_run_links_pending
            ON automation_run_links(status, created_at, id);
        """,
    ),
    Migration(
        version=17,
        sql="""
        CREATE TABLE mcp_connections (
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            preset_id TEXT NOT NULL,
            preset_version TEXT NOT NULL,
            installed INTEGER NOT NULL,
            enabled INTEGER NOT NULL,
            health TEXT NOT NULL,
            tool_ids TEXT NOT NULL,
            installed_at TEXT,
            checked_at TEXT,
            PRIMARY KEY(workspace_id, preset_id)
        );
        CREATE INDEX idx_mcp_connections_enabled
            ON mcp_connections(enabled, workspace_id, preset_id);
        """,
    ),
    Migration(
        version=18,
        sql="""
        CREATE TABLE run_connector_routes (
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            connector TEXT NOT NULL,
            account_id TEXT NOT NULL,
            external_account_id TEXT NOT NULL,
            conversation_grant_revision INTEGER NOT NULL,
            bound_at TEXT NOT NULL,
            PRIMARY KEY(run_id, connector),
            CHECK(conversation_grant_revision >= 1)
        );
        CREATE INDEX idx_run_connector_routes_workspace
            ON run_connector_routes(workspace_id, bound_at, run_id);
        """,
    ),
    Migration(
        version=19,
        sql="""
        CREATE TABLE conversation_sessions (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0, 1)),
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_conversation_sessions_workspace
            ON conversation_sessions(workspace_id, pinned DESC, updated_at DESC, id DESC);

        ALTER TABLE runs ADD COLUMN session_id TEXT
            REFERENCES conversation_sessions(id) ON DELETE SET NULL;
        CREATE INDEX idx_runs_session
            ON runs(session_id, updated_at DESC, id DESC);
        """,
    ),
    Migration(
        version=20,
        sql="""
        CREATE TABLE connector_account_migration_map (
            old_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            new_id TEXT NOT NULL UNIQUE,
            PRIMARY KEY(old_id, workspace_id)
        );

        INSERT INTO connector_account_migration_map(old_id, workspace_id, new_id)
        SELECT
            ownership.account_id,
            ownership.workspace_id,
            CASE
                WHEN ownership.workspace_id = (
                    SELECT MIN(candidate.workspace_id)
                    FROM (
                        SELECT account_id, workspace_id FROM connector_bindings
                        UNION
                        SELECT account_id, workspace_id FROM connection_attempts
                        UNION
                        SELECT account_id, workspace_id FROM run_connector_routes
                    ) AS candidate
                    WHERE candidate.account_id = ownership.account_id
                ) THEN ownership.account_id
                ELSE ownership.account_id || '__wfws__' || ownership.workspace_id
            END
        FROM (
            SELECT account_id, workspace_id FROM connector_bindings
            UNION
            SELECT account_id, workspace_id FROM connection_attempts
            UNION
            SELECT account_id, workspace_id FROM run_connector_routes
        ) AS ownership;

        CREATE TABLE connector_accounts_v20 (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            connector TEXT NOT NULL,
            external_account_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            config TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(workspace_id, connector, id)
        );

        INSERT INTO connector_accounts_v20(
            id, workspace_id, connector, external_account_id, phase, config,
            version, created_at, updated_at
        )
        SELECT
            mapping.new_id,
            mapping.workspace_id,
            account.connector,
            account.external_account_id,
            account.phase,
            json_set(
                account.config,
                '$.id', mapping.new_id,
                '$.workspace_id', mapping.workspace_id
            ),
            account.version,
            account.created_at,
            account.updated_at
        FROM connector_account_migration_map AS mapping
        JOIN connector_accounts AS account ON account.id = mapping.old_id;

        CREATE TABLE connection_attempts_v20 (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            connector TEXT NOT NULL,
            account_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            config TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id, connector, account_id)
                REFERENCES connector_accounts_v20(workspace_id, connector, id)
                ON DELETE CASCADE
        );

        INSERT INTO connection_attempts_v20(
            id, workspace_id, connector, account_id, phase, expires_at,
            config, created_at, updated_at
        )
        SELECT
            attempt.id,
            attempt.workspace_id,
            attempt.connector,
            mapping.new_id,
            attempt.phase,
            attempt.expires_at,
            json_set(attempt.config, '$.account_id', mapping.new_id),
            attempt.created_at,
            attempt.updated_at
        FROM connection_attempts AS attempt
        JOIN connector_account_migration_map AS mapping
          ON mapping.old_id = attempt.account_id
         AND mapping.workspace_id = attempt.workspace_id;

        CREATE TABLE connector_bindings_v20 (
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            connector TEXT NOT NULL,
            account_id TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            auto_fetch_enabled INTEGER NOT NULL,
            next_sync_at TEXT NOT NULL,
            config TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(workspace_id, connector),
            FOREIGN KEY(workspace_id, connector, account_id)
                REFERENCES connector_accounts_v20(workspace_id, connector, id)
                ON DELETE CASCADE
        );

        INSERT INTO connector_bindings_v20(
            workspace_id, connector, account_id, enabled, auto_fetch_enabled,
            next_sync_at, config, version, created_at, updated_at
        )
        SELECT
            binding.workspace_id,
            binding.connector,
            mapping.new_id,
            binding.enabled,
            binding.auto_fetch_enabled,
            binding.next_sync_at,
            json_set(binding.config, '$.account_id', mapping.new_id),
            binding.version,
            binding.created_at,
            binding.updated_at
        FROM connector_bindings AS binding
        JOIN connector_account_migration_map AS mapping
          ON mapping.old_id = binding.account_id
         AND mapping.workspace_id = binding.workspace_id;

        UPDATE run_connector_routes
        SET account_id = (
            SELECT mapping.new_id
            FROM connector_account_migration_map AS mapping
            WHERE mapping.old_id = run_connector_routes.account_id
              AND mapping.workspace_id = run_connector_routes.workspace_id
        )
        WHERE EXISTS (
            SELECT 1
            FROM connector_account_migration_map AS mapping
            WHERE mapping.old_id = run_connector_routes.account_id
              AND mapping.workspace_id = run_connector_routes.workspace_id
        );

        CREATE UNIQUE INDEX idx_runs_id_workspace
            ON runs(id, workspace_id);

        CREATE TABLE run_connector_routes_v20 (
            run_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            connector TEXT NOT NULL,
            account_id TEXT NOT NULL,
            external_account_id TEXT NOT NULL,
            conversation_grant_revision INTEGER NOT NULL,
            bound_at TEXT NOT NULL,
            PRIMARY KEY(run_id, connector),
            FOREIGN KEY(run_id, workspace_id)
                REFERENCES runs(id, workspace_id) ON DELETE CASCADE,
            CHECK(conversation_grant_revision >= 1)
        );

        INSERT INTO run_connector_routes_v20(
            run_id, workspace_id, connector, account_id,
            external_account_id, conversation_grant_revision, bound_at
        )
        SELECT
            run_id, workspace_id, connector, account_id,
            external_account_id, conversation_grant_revision, bound_at
        FROM run_connector_routes;

        DROP TABLE run_connector_routes;
        DROP TABLE connection_attempts;
        DROP TABLE connector_bindings;
        DROP TABLE connector_accounts;

        ALTER TABLE connector_accounts_v20 RENAME TO connector_accounts;
        ALTER TABLE connection_attempts_v20 RENAME TO connection_attempts;
        ALTER TABLE connector_bindings_v20 RENAME TO connector_bindings;
        ALTER TABLE run_connector_routes_v20 RENAME TO run_connector_routes;

        CREATE INDEX idx_connector_accounts_workspace_connector
            ON connector_accounts(workspace_id, connector, updated_at DESC, id DESC);
        CREATE INDEX idx_connection_attempts_connector
            ON connection_attempts(workspace_id, connector, created_at DESC, id DESC);
        CREATE INDEX idx_connector_bindings_due
            ON connector_bindings(enabled, auto_fetch_enabled, next_sync_at);
        CREATE INDEX idx_run_connector_routes_workspace
            ON run_connector_routes(workspace_id, bound_at, run_id);

        DROP TABLE connector_account_migration_map;
        """,
    ),
)
