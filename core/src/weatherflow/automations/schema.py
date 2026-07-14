AUTOMATION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS automations (
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
CREATE INDEX IF NOT EXISTS idx_automations_workspace_status
    ON automations(workspace_id, status, updated_at, id);
CREATE INDEX IF NOT EXISTS idx_automations_due
    ON automations(status, next_run_at, id);

CREATE TABLE IF NOT EXISTS automation_run_links (
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
CREATE INDEX IF NOT EXISTS idx_automation_run_links_history
    ON automation_run_links(automation_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_automation_run_links_pending
    ON automation_run_links(status, created_at, id);
"""
