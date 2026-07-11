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
)
