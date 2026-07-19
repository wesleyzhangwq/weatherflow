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
    Migration(
        version=21,
        sql="""
        CREATE TABLE run_controls (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('steer', 'follow_up')),
            content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 20000),
            status TEXT NOT NULL CHECK(status IN ('pending', 'applied')),
            created_at TEXT NOT NULL,
            applied_at TEXT,
            applied_step_index INTEGER,
            CHECK(
                (status = 'pending' AND applied_at IS NULL AND applied_step_index IS NULL)
                OR
                (status = 'applied' AND applied_at IS NOT NULL AND applied_step_index IS NOT NULL)
            )
        );

        CREATE INDEX idx_run_controls_pending
            ON run_controls(run_id, status, created_at, id);
        """,
    ),
    Migration(
        version=22,
        sql="""
        ALTER TABLE runs
            ADD COLUMN tool_mode TEXT NOT NULL DEFAULT 'ask'
            CHECK(tool_mode IN ('ask', 'bypass'));

        UPDATE runs
        SET tool_mode = 'bypass'
        WHERE EXISTS (
            SELECT 1
            FROM capability_snapshots AS snapshot,
                 json_each(snapshot.tools) AS tool
            WHERE snapshot.run_id = runs.id
              AND json_extract(tool.value, '$.effect')
                  NOT IN ('observe', 'network_read')
        );

        CREATE TABLE run_connector_routes_v22 (
            run_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            connector TEXT NOT NULL,
            account_id TEXT NOT NULL,
            external_account_id TEXT NOT NULL,
            bound_at TEXT NOT NULL,
            PRIMARY KEY(run_id, connector),
            FOREIGN KEY(run_id, workspace_id)
                REFERENCES runs(id, workspace_id) ON DELETE CASCADE
        );

        INSERT INTO run_connector_routes_v22(
            run_id, workspace_id, connector, account_id,
            external_account_id, bound_at
        )
        SELECT
            run_id, workspace_id, connector, account_id,
            external_account_id, bound_at
        FROM run_connector_routes;

        DROP TABLE run_connector_routes;
        ALTER TABLE run_connector_routes_v22 RENAME TO run_connector_routes;
        CREATE INDEX idx_run_connector_routes_workspace
            ON run_connector_routes(workspace_id, bound_at, run_id);
        """,
    ),
    Migration(
        version=23,
        sql="""
        CREATE TABLE connector_bindings_v23 (
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
                REFERENCES connector_accounts(workspace_id, connector, id)
                ON DELETE CASCADE
        );

        INSERT INTO connector_bindings_v23(
            workspace_id, connector, account_id, enabled, auto_fetch_enabled,
            next_sync_at, config, version, created_at, updated_at
        )
        SELECT
            workspace_id,
            connector,
            account_id,
            enabled,
            auto_fetch_enabled,
            next_sync_at,
            json_remove(
                config,
                '$.conversation_access',
                '$.conversation_tool_ids',
                '$.conversation_grant_revision'
            ),
            version,
            created_at,
            updated_at
        FROM connector_bindings;

        DROP TABLE connector_bindings;
        ALTER TABLE connector_bindings_v23 RENAME TO connector_bindings;
        CREATE INDEX idx_connector_bindings_due
            ON connector_bindings(enabled, auto_fetch_enabled, next_sync_at);
        """,
    ),
    Migration(
        version=24,
        sql="""
        CREATE TABLE activity_preferences (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            config TEXT NOT NULL,
            version INTEGER NOT NULL CHECK(version >= 0),
            updated_at TEXT NOT NULL
        );

        CREATE TABLE activity_events (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL CHECK(source IN ('macos_window', 'browser_tab', 'idle')),
            device_id TEXT NOT NULL,
            source_instance TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            duration_seconds REAL NOT NULL CHECK(duration_seconds >= 0),
            app_name TEXT,
            bundle_id TEXT,
            window_title TEXT,
            browser_name TEXT,
            browser_window_id TEXT,
            browser_tab_id TEXT,
            url TEXT,
            domain TEXT,
            tab_title TEXT,
            audible INTEGER,
            incognito INTEGER,
            focused INTEGER,
            idle_state TEXT NOT NULL CHECK(idle_state IN ('active', 'idle', 'unknown')),
            category TEXT,
            state_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX idx_activity_events_interval
            ON activity_events(started_at, ended_at, id);
        CREATE INDEX idx_activity_events_source_interval
            ON activity_events(source, started_at, ended_at, id);
        CREATE INDEX idx_activity_events_source_instance
            ON activity_events(source_instance, ended_at DESC, id DESC);
        CREATE INDEX idx_activity_events_app
            ON activity_events(app_name, started_at, id);
        CREATE INDEX idx_activity_events_domain
            ON activity_events(domain, started_at, id);

        CREATE TABLE activity_heartbeat_receipts (
            source_instance TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            activity_event_id TEXT NOT NULL REFERENCES activity_events(id) ON DELETE CASCADE,
            observed_at TEXT NOT NULL,
            PRIMARY KEY(source_instance, source_event_id)
        );

        CREATE INDEX idx_activity_heartbeat_receipts_event
            ON activity_heartbeat_receipts(activity_event_id);
        """,
    ),
    Migration(
        version=25,
        sql="""
        CREATE TABLE activity_inference_jobs (
            id TEXT PRIMARY KEY,
            scheduled_for TEXT NOT NULL UNIQUE,
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN (
                'pending', 'executing', 'completed', 'failed', 'needs_review'
            )),
            config TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX idx_activity_inference_jobs_status_schedule
            ON activity_inference_jobs(status, scheduled_for, id);
        """,
    ),
    Migration(
        version=26,
        sql="""
        ALTER TABLE activity_events ADD COLUMN source_event_id TEXT;
        UPDATE activity_events SET source_event_id = id WHERE source_event_id IS NULL;
        CREATE INDEX idx_activity_events_source_event
            ON activity_events(source_instance, source_event_id);
        """,
    ),
    Migration(
        version=27,
        sql="""
        DROP TABLE activity_inference_jobs;
        DROP TABLE activity_heartbeat_receipts;
        DROP TABLE activity_events;
        DROP TABLE activity_preferences;

        CREATE TABLE activity_source_state (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            health TEXT NOT NULL CHECK(health IN ('available', 'degraded')),
            config TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE activity_category_rule_versions (
            id TEXT PRIMARY KEY CHECK(length(id) = 64),
            canonical_json TEXT NOT NULL,
            rule_count INTEGER NOT NULL CHECK(rule_count >= 0),
            created_at TEXT NOT NULL
        );

        CREATE TABLE activity_summary_tasks (
            id TEXT PRIMARY KEY,
            task_type TEXT NOT NULL CHECK(task_type IN (
                'stage_6h', 'daily_24h', 'weekly', 'biweekly', 'monthly'
            )),
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            timezone TEXT NOT NULL CHECK(timezone = 'Asia/Shanghai'),
            boundary_policy_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN (
                'pending', 'running', 'completed', 'failed', 'needs_retry'
            )),
            finality TEXT CHECK(finality IS NULL OR finality IN ('provisional', 'final')),
            attempt_count INTEGER NOT NULL CHECK(attempt_count >= 0),
            not_before TEXT NOT NULL,
            next_retry_at TEXT,
            lease_owner TEXT,
            lease_expires_at TEXT,
            current_revision INTEGER NOT NULL CHECK(current_revision >= 0),
            category_rule_version TEXT
                REFERENCES activity_category_rule_versions(id),
            source_watermark TEXT,
            config TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(
                task_type,
                timezone,
                boundary_policy_version,
                window_start,
                window_end
            ),
            CHECK(window_end > window_start)
        );

        CREATE INDEX idx_activity_summary_tasks_due
            ON activity_summary_tasks(
                status,
                not_before,
                next_retry_at,
                window_end
            );

        CREATE TABLE activity_summary_attempts (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL
                REFERENCES activity_summary_tasks(id) ON DELETE CASCADE,
            attempt_number INTEGER NOT NULL CHECK(attempt_number >= 1),
            status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
            config TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE(task_id, attempt_number)
        );

        CREATE INDEX idx_activity_summary_attempts_task
            ON activity_summary_attempts(task_id, attempt_number);

        CREATE TABLE activity_summary_revisions (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL
                REFERENCES activity_summary_tasks(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL CHECK(revision_number >= 1),
            finality TEXT NOT NULL CHECK(finality IN ('provisional', 'final')),
            source_watermark TEXT NOT NULL,
            category_rule_version TEXT NOT NULL
                REFERENCES activity_category_rule_versions(id),
            revision_key TEXT NOT NULL UNIQUE,
            config TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            UNIQUE(task_id, revision_number)
        );

        CREATE INDEX idx_activity_summary_revisions_task
            ON activity_summary_revisions(task_id, revision_number DESC);

        CREATE TABLE activity_summary_dependencies (
            parent_task_id TEXT NOT NULL
                REFERENCES activity_summary_tasks(id) ON DELETE CASCADE,
            child_task_id TEXT NOT NULL
                REFERENCES activity_summary_tasks(id) ON DELETE CASCADE,
            PRIMARY KEY(parent_task_id, child_task_id),
            CHECK(parent_task_id != child_task_id)
        );

        CREATE INDEX idx_activity_summary_dependencies_child
            ON activity_summary_dependencies(child_task_id, parent_task_id);

        CREATE TABLE activity_statistics (
            revision_id TEXT PRIMARY KEY
                REFERENCES activity_summary_revisions(id) ON DELETE CASCADE,
            config TEXT NOT NULL
        );

        CREATE TABLE activity_state_inferences (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL
                REFERENCES activity_summary_tasks(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL CHECK(revision_number >= 1),
            label TEXT NOT NULL CHECK(label IN (
                'programming',
                'communication',
                'meeting',
                'focus',
                'context_fragmentation'
            )),
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            valid_from TEXT NOT NULL,
            valid_until TEXT NOT NULL,
            config TEXT NOT NULL,
            created_at TEXT NOT NULL,
            CHECK(valid_until > valid_from)
        );

        CREATE INDEX idx_activity_state_inferences_task
            ON activity_state_inferences(task_id, revision_number, created_at, id);
        CREATE INDEX idx_activity_state_inferences_validity
            ON activity_state_inferences(valid_until, created_at, id);

        CREATE TABLE activity_evidence_refs (
            owner_type TEXT NOT NULL CHECK(owner_type IN ('revision', 'inference')),
            owner_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            bucket_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_timestamp TEXT NOT NULL,
            event_digest TEXT NOT NULL CHECK(length(event_digest) = 64),
            config TEXT NOT NULL,
            PRIMARY KEY(owner_type, owner_id, ordinal)
        );

        CREATE INDEX idx_activity_evidence_refs_event
            ON activity_evidence_refs(bucket_id, event_id);
        """,
    ),
    Migration(
        version=28,
        sql="""
        CREATE TABLE activity_live_inferences (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL CHECK(label IN (
                'programming',
                'communication',
                'meeting',
                'focus',
                'context_fragmentation'
            )),
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            valid_from TEXT NOT NULL,
            valid_until TEXT NOT NULL,
            source_watermark TEXT NOT NULL CHECK(length(source_watermark) = 64),
            config TEXT NOT NULL,
            created_at TEXT NOT NULL,
            CHECK(valid_until > valid_from)
        );

        CREATE INDEX idx_activity_live_inferences_current
            ON activity_live_inferences(valid_until DESC, created_at DESC, id DESC);

        CREATE TABLE activity_live_evidence_refs (
            inference_id TEXT NOT NULL
                REFERENCES activity_live_inferences(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            bucket_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_timestamp TEXT NOT NULL,
            event_digest TEXT NOT NULL CHECK(length(event_digest) = 64),
            config TEXT NOT NULL,
            PRIMARY KEY(inference_id, ordinal)
        );

        CREATE INDEX idx_activity_live_evidence_refs_event
            ON activity_live_evidence_refs(bucket_id, event_id);
        """,
    ),
    Migration(
        version=29,
        sql="""
        CREATE TEMP TABLE migration29_legacy_activity_events AS
        SELECT
            id,
            CASE
                WHEN stream_kind = 'workspace' THEN stream_id
                ELSE correlation_id
            END AS workspace_id
        FROM events
        WHERE type = 'rhythm.signal.activity_metadata';

        CREATE TEMP TABLE migration29_affected_rhythm_events AS
        SELECT
            event.id AS event_id,
            event.stream_id AS snapshot_id,
            event.correlation_id AS workspace_id
        FROM events AS event
        WHERE (
            event.type = 'rhythm.snapshot_derived'
            AND EXISTS (
                SELECT 1
                FROM json_each(event.payload, '$.supporting_event_ids') AS reference
                JOIN migration29_legacy_activity_events AS legacy
                    ON legacy.id = reference.value
            )
        ) OR (
            event.type = 'rhythm.snapshot_remote_inference'
            AND EXISTS (
                SELECT 1
                FROM json_each(event.payload, '$.evidence_event_ids') AS reference
                JOIN migration29_legacy_activity_events AS legacy
                    ON legacy.id = reference.value
            )
        );

        CREATE TEMP TABLE migration29_affected_snapshot_ids AS
        SELECT DISTINCT snapshot_id
        FROM migration29_affected_rhythm_events
        WHERE snapshot_id IS NOT NULL
        UNION
        SELECT DISTINCT json_extract(snapshot, '$.id')
        FROM rhythm_snapshots
        WHERE workspace_id IN (
            SELECT DISTINCT workspace_id
            FROM migration29_legacy_activity_events
        );

        CREATE TEMP TABLE migration29_affected_episodes AS
        SELECT memory.id
        FROM episodic_memories AS memory
        WHERE EXISTS (
            SELECT 1
            FROM json_each(memory.source_event_ids) AS reference
            JOIN migration29_legacy_activity_events AS legacy
                ON legacy.id = reference.value
        );

        CREATE TEMP TABLE migration29_affected_profiles AS
        SELECT assertion.id
        FROM profile_assertions AS assertion
        WHERE EXISTS (
            SELECT 1
            FROM json_each(assertion.evidence_event_ids) AS reference
            JOIN migration29_legacy_activity_events AS legacy
                ON legacy.id = reference.value
        );

        UPDATE runs
        SET rhythm_snapshot_id = NULL
        WHERE rhythm_snapshot_id IN (
            SELECT snapshot_id
            FROM migration29_affected_snapshot_ids
        );

        DELETE FROM memory_search_index
        WHERE (
            entry_kind = 'episode'
            AND entry_id IN (
                SELECT id FROM migration29_affected_episodes
            )
        ) OR (
            entry_kind = 'profile_assertion'
            AND entry_id IN (
                SELECT id FROM migration29_affected_profiles
            )
        );

        DELETE FROM events
        WHERE (
            stream_kind = 'episodic_memory'
            AND stream_id IN (
                SELECT id FROM migration29_affected_episodes
            )
        ) OR (
            stream_kind = 'profile_assertion'
            AND stream_id IN (
                SELECT id FROM migration29_affected_profiles
            )
        );

        DELETE FROM episodic_memories
        WHERE id IN (
            SELECT id FROM migration29_affected_episodes
        );

        DELETE FROM profile_assertions
        WHERE id IN (
            SELECT id FROM migration29_affected_profiles
        );

        DELETE FROM events
        WHERE id IN (
            SELECT event_id
            FROM migration29_affected_rhythm_events
        );

        DELETE FROM rhythm_snapshots
        WHERE workspace_id IN (
            SELECT DISTINCT workspace_id
            FROM migration29_legacy_activity_events
        );

        DELETE FROM events
        WHERE id IN (
            SELECT id
            FROM migration29_legacy_activity_events
        );

        DROP TABLE migration29_affected_profiles;
        DROP TABLE migration29_affected_episodes;
        DROP TABLE migration29_affected_snapshot_ids;
        DROP TABLE migration29_affected_rhythm_events;
        DROP TABLE migration29_legacy_activity_events;
        """,
    ),
    Migration(
        version=30,
        sql="""
        CREATE TABLE IF NOT EXISTS privacy_compaction_requests (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO privacy_compaction_requests(id)
        VALUES (1)
        ON CONFLICT(id) DO UPDATE SET requested_at = CURRENT_TIMESTAMP;
        """,
    ),
    Migration(
        version=31,
        sql="""
        -- Migration 23 was amended during development after some local databases
        -- had already recorded it as applied. Repair those installed rows with a
        -- new immutable migration so strict ConnectorBinding validation cannot
        -- take down Run submission or the OAuth catalog.
        UPDATE connector_bindings
        SET config = json_remove(
            config,
            '$.conversation_access',
            '$.conversation_tool_ids',
            '$.conversation_grant_revision'
        )
        WHERE json_type(config, '$.conversation_access') IS NOT NULL
           OR json_type(config, '$.conversation_tool_ids') IS NOT NULL
           OR json_type(config, '$.conversation_grant_revision') IS NOT NULL;
        """,
    ),
    Migration(
        version=32,
        sql="""
        CREATE TABLE activity_summary_settings (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            version INTEGER NOT NULL CHECK(version >= 0),
            config TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
    Migration(
        version=33,
        sql="""
        -- Application and domain labels are ActivityWatch-owned raw facts. Older
        -- summary revisions embedded those query-time labels in both statistics
        -- maps and, potentially, their generated narrative. Keep only label-free
        -- totals, Category-derived statistics, and evidence references durably.
        UPDATE activity_summary_revisions
        SET config = json_set(
            json_remove(
                config,
                '$.statistics.application_seconds',
                '$.statistics.domain_seconds'
            ),
            '$.summary_text',
            printf(
                'Historical activity summary retained after privacy cleanup. '
                || 'Active seconds: %g; AFK seconds: %g; context switches: %d. '
                || 'Application and domain labels were removed.',
                COALESCE(json_extract(config, '$.statistics.active_seconds'), 0),
                COALESCE(json_extract(config, '$.statistics.afk_seconds'), 0),
                COALESCE(json_extract(config, '$.statistics.context_switch_count'), 0)
            )
        )
        WHERE EXISTS (
                SELECT 1
                FROM json_each(
                    activity_summary_revisions.config,
                    '$.statistics.application_seconds'
                )
            )
           OR EXISTS (
                SELECT 1
                FROM json_each(
                    activity_summary_revisions.config,
                    '$.statistics.domain_seconds'
                )
            );

        UPDATE activity_summary_revisions
        SET config = json_remove(
            config,
            '$.statistics.application_seconds',
            '$.statistics.domain_seconds'
        )
        WHERE json_type(config, '$.statistics.application_seconds') IS NOT NULL
           OR json_type(config, '$.statistics.domain_seconds') IS NOT NULL;

        UPDATE activity_statistics
        SET config = json_remove(
            config,
            '$.application_seconds',
            '$.domain_seconds'
        )
        WHERE json_type(config, '$.application_seconds') IS NOT NULL
           OR json_type(config, '$.domain_seconds') IS NOT NULL;

        -- Reclaim pages and truncate the WAL after initialize() commits this
        -- privacy migration so removed labels do not linger in SQLite free space.
        INSERT INTO privacy_compaction_requests(id)
        VALUES (1)
        ON CONFLICT(id) DO UPDATE SET requested_at = CURRENT_TIMESTAMP;
        """,
    ),
    Migration(
        version=34,
        sql="""
        CREATE TABLE activity_live_state_assessments (
            id TEXT PRIMARY KEY CHECK(length(id) = 64),
            workspace_id TEXT NOT NULL
                REFERENCES workspaces(id) ON DELETE CASCADE,
            status TEXT NOT NULL CHECK(status IN ('available', 'degraded')),
            source_watermark TEXT NOT NULL CHECK(length(source_watermark) = 64),
            config TEXT NOT NULL,
            assessed_at TEXT NOT NULL,
            UNIQUE(workspace_id, source_watermark)
        );

        CREATE INDEX idx_activity_live_state_assessments_workspace
            ON activity_live_state_assessments(workspace_id, assessed_at DESC, id DESC);
        """,
    ),
    Migration(
        version=35,
        sql="""
        -- ActivityWatch state inference and comprehensive live assessments are
        -- no longer WeatherFlow-owned data. Preserve only evidence references
        -- attached to durable summary revisions.
        CREATE TABLE activity_evidence_refs_v35 (
            owner_type TEXT NOT NULL CHECK(owner_type = 'revision'),
            owner_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            bucket_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_timestamp TEXT NOT NULL,
            event_digest TEXT NOT NULL CHECK(length(event_digest) = 64),
            config TEXT NOT NULL,
            PRIMARY KEY(owner_type, owner_id, ordinal)
        );

        INSERT INTO activity_evidence_refs_v35(
            owner_type, owner_id, ordinal, bucket_id, event_id,
            event_timestamp, event_digest, config
        )
        SELECT
            owner_type, owner_id, ordinal, bucket_id, event_id,
            event_timestamp, event_digest, config
        FROM activity_evidence_refs
        WHERE owner_type = 'revision';

        DROP TABLE activity_evidence_refs;
        ALTER TABLE activity_evidence_refs_v35 RENAME TO activity_evidence_refs;
        CREATE INDEX idx_activity_evidence_refs_event
            ON activity_evidence_refs(bucket_id, event_id);

        DROP TABLE activity_live_state_assessments;
        DROP TABLE activity_live_evidence_refs;
        DROP TABLE activity_live_inferences;
        DROP TABLE activity_state_inferences;

        UPDATE activity_source_state
        SET config = json_remove(config, '$.last_live_inference_checked_at')
        WHERE json_type(config, '$.last_live_inference_checked_at') IS NOT NULL;

        -- Reclaim pages and truncate the WAL so removed inference narratives
        -- and evidence cannot remain recoverable in SQLite free space.
        INSERT INTO privacy_compaction_requests(id)
        VALUES (1)
        ON CONFLICT(id) DO UPDATE SET requested_at = CURRENT_TIMESTAMP;
        """,
    ),
    Migration(
        version=36,
        sql="""
        -- Summary prose is now governed by one code-owned, versioned Chinese
        -- contract. Remove every persisted user-authored prompt while retaining
        -- the immutable prompt version on historical revisions.
        UPDATE activity_summary_settings
        SET version = version + 1,
            config = json_set(
                json_remove(config, '$.prompt'),
                '$.prompt_version',
                'activity-summary-prompt-v3-zh-fixed:872e7d7b47088207',
                '$.version',
                version + 1,
                '$.updated_at',
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');

        -- Re-run every task whose current revision used an older prompt. The
        -- old revision remains immutable; recovery appends a new Chinese one.
        UPDATE activity_summary_tasks
        SET status = 'needs_retry',
            next_retry_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            config = json_set(
                config,
                '$.status', 'needs_retry',
                '$.next_retry_at', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                '$.completed_at', NULL,
                '$.error_code', NULL,
                '$.regeneration_reason', 'fixed_chinese_prompt_v3',
                '$.updated_at', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            )
        WHERE status = 'completed'
          AND COALESCE(json_extract(config, '$.prompt_version'), '')
              <> 'activity-summary-prompt-v3-zh-fixed:872e7d7b47088207';

        INSERT INTO privacy_compaction_requests(id)
        VALUES (1)
        ON CONFLICT(id) DO UPDATE SET requested_at = CURRENT_TIMESTAMP;
        """,
    ),
    Migration(
        version=37,
        sql="""
        -- The production connector schedule is one fixed daily cadence. A
        -- parser/strategy upgrade must not leave an old false-empty snapshot
        -- visible until a future legacy deadline, so enabled sources become due
        -- once immediately. Every subsequent attempt schedules the following
        -- run 1440 minutes later through the domain model.
        UPDATE connector_bindings
        SET config = json_set(
                config,
                '$.interval_minutes', 1440,
                '$.fetch_contract_version',
                'connector-fetch-v2-daily-source-specific'
            )
        WHERE connector IN ('github', 'gmail', 'google_calendar')
          AND (
              COALESCE(json_extract(config, '$.interval_minutes'), 0) <> 1440
              OR COALESCE(json_extract(config, '$.fetch_contract_version'), '')
                  <> 'connector-fetch-v2-daily-source-specific'
          );

        UPDATE connector_bindings
        SET next_sync_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            version = version + 1,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            config = json_set(
                config,
                '$.interval_minutes', 1440,
                '$.fetch_contract_version',
                'connector-fetch-v2-daily-source-specific',
                '$.next_sync_at', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                '$.version', version + 1,
                '$.updated_at', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            )
        WHERE connector IN ('github', 'gmail', 'google_calendar')
          AND enabled = 1
          AND auto_fetch_enabled = 1;
        """,
    ),
    Migration(
        version=38,
        sql="""
        -- The fixed Chinese summary contract now prioritizes bounded temporal
        -- sequences and evidence traceability instead of metric-list prose.
        UPDATE activity_summary_settings
        SET version = version + 1,
            config = json_set(
                config,
                '$.prompt_version',
                'activity-summary-prompt-v4-context-sequence-zh-fixed:ff78a64bf2e4177e',
                '$.version',
                version + 1,
                '$.updated_at',
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');

        -- Preserve old revisions and let startup recovery append one revision
        -- under the new prompt. Do not infer gaps from a last-run timestamp.
        UPDATE activity_summary_tasks
        SET status = 'needs_retry',
            next_retry_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            config = json_set(
                config,
                '$.status', 'needs_retry',
                '$.next_retry_at', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                '$.completed_at', NULL,
                '$.error_code', NULL,
                '$.regeneration_reason', 'context_sequence_prompt_v4',
                '$.updated_at', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            )
        WHERE status = 'completed'
          AND COALESCE(json_extract(config, '$.prompt_version'), '')
              <> 'activity-summary-prompt-v4-context-sequence-zh-fixed:ff78a64bf2e4177e';
        """,
    ),
    Migration(
        version=39,
        sql="""
        -- Repair installations that recorded the development form of migration
        -- 37 before the source-specific parser/strategy version was added. New
        -- databases already carry this marker and this migration is a no-op.
        UPDATE connector_bindings
        SET next_sync_at = CASE
                WHEN enabled = 1 AND auto_fetch_enabled = 1
                THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                ELSE next_sync_at
            END,
            version = version + 1,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            config = json_set(
                config,
                '$.interval_minutes', 1440,
                '$.fetch_contract_version',
                'connector-fetch-v2-daily-source-specific',
                '$.next_sync_at', CASE
                    WHEN enabled = 1 AND auto_fetch_enabled = 1
                    THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    ELSE next_sync_at
                END,
                '$.version', version + 1,
                '$.updated_at', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            )
        WHERE connector IN ('github', 'gmail', 'google_calendar')
          AND COALESCE(json_extract(config, '$.fetch_contract_version'), '')
              <> 'connector-fetch-v2-daily-source-specific';
        """,
    ),
    Migration(
        version=40,
        sql="""
        -- Tighten the context-sequence prompt so raw application names and
        -- source-text fragments cannot be retained in durable summary prose.
        UPDATE activity_summary_settings
        SET version = version + 1,
            config = json_set(
                config,
                '$.prompt_version',
                'activity-summary-prompt-v5-privacy-context-sequence-zh-fixed:791413eefa7f8a0c',
                '$.version',
                version + 1,
                '$.updated_at',
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');

        UPDATE activity_summary_tasks
        SET status = 'needs_retry',
            next_retry_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            config = json_set(
                config,
                '$.status', 'needs_retry',
                '$.next_retry_at', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                '$.completed_at', NULL,
                '$.error_code', NULL,
                '$.regeneration_reason', 'privacy_context_sequence_prompt_v5',
                '$.updated_at', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            )
        WHERE status = 'completed'
          AND COALESCE(json_extract(config, '$.prompt_version'), '')
              <> 'activity-summary-prompt-v5-privacy-context-sequence-zh-fixed:791413eefa7f8a0c';

        UPDATE activity_summary_tasks
        SET config = json_set(
                config,
                '$.regeneration_reason', 'privacy_context_sequence_prompt_v5'
            )
        WHERE status = 'needs_retry'
          AND json_extract(config, '$.regeneration_reason') IN (
              'fixed_chinese_prompt_v3',
              'context_sequence_prompt_v4'
          );
        """,
    ),
    Migration(
        version=41,
        sql="""
        -- Old prompt revisions may contain an application alias, source-text
        -- fragment, or forbidden human-state claim. Privacy deletion outranks
        -- immutable revision retention: keep statistics and digest provenance,
        -- but remove unsafe prose until recovery appends a v5 revision.
        UPDATE activity_summary_revisions
        SET config = json_set(
                config,
                '$.summary_text',
                '该历史总结使用旧版隐私合同生成，正文已移除；' ||
                '统计与证据引用可从 ActivityWatch 重新计算。'
            )
        WHERE COALESCE(json_extract(config, '$.prompt_version'), '')
              <> 'activity-summary-prompt-v5-privacy-context-sequence-zh-fixed:791413eefa7f8a0c'
          AND COALESCE(json_extract(config, '$.summary_text'), '')
              <> ('该历史总结使用旧版隐私合同生成，正文已移除；' ||
                  '统计与证据引用可从 ActivityWatch 重新计算。');

        INSERT INTO privacy_compaction_requests(id)
        VALUES (1)
        ON CONFLICT(id) DO UPDATE SET requested_at = CURRENT_TIMESTAMP;
        """,
    ),
    Migration(
        version=42,
        sql="""
        -- Builds before v42 could complete a configured remote-model summary
        -- with deterministic prose when Keychain or provider connectivity was
        -- temporarily unavailable. Preserve every immutable revision and its
        -- evidence, but put only tasks whose latest revision has a transient
        -- transport fallback back into the idempotent compensation ledger.
        UPDATE activity_summary_tasks
        SET status = 'needs_retry',
            next_retry_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            config = json_set(
                config,
                '$.status', 'needs_retry',
                '$.next_retry_at', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                '$.completed_at', NULL,
                '$.error_code', NULL,
                '$.regeneration_reason',
                'transient_model_fallback_recovery_v1',
                '$.updated_at', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            )
        WHERE status = 'completed'
          AND EXISTS (
              SELECT 1
              FROM activity_summary_revisions AS revision
              WHERE revision.task_id = activity_summary_tasks.id
                AND revision.revision_number = (
                    SELECT MAX(latest.revision_number)
                    FROM activity_summary_revisions AS latest
                    WHERE latest.task_id = activity_summary_tasks.id
                )
                AND COALESCE(
                    json_extract(revision.config, '$.fallback_reason'),
                    ''
                ) IN (
                    'activity_model_authentication_failed',
                    'activity_model_temporarily_unavailable',
                    'activity_model_connection_failed'
                )
          );
        """,
    ),
)
