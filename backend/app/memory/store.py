"""SQLite + FTS5 schema and connection helpers."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from app.config import get_settings


_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT    NOT NULL,                -- YYYY-MM-DD
    status      TEXT,
    did_today   TEXT,
    stuck_on    TEXT,
    anxiety     TEXT,
    raw         TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_checkins_date ON checkins(date);

CREATE TABLE IF NOT EXISTS reflections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT    NOT NULL,
    kind        TEXT    NOT NULL CHECK (kind IN ('daily','weekly')),
    content     TEXT    NOT NULL,
    insights    TEXT,                              -- JSON
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reflections_kind_date ON reflections(kind, date DESC);

CREATE TABLE IF NOT EXISTS state_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL DEFAULT (datetime('now')),
    focus         INTEGER NOT NULL,
    stress        INTEGER NOT NULL,
    burnout       INTEGER NOT NULL,
    momentum      INTEGER NOT NULL,
    confidence    INTEGER NOT NULL,
    motivation    INTEGER NOT NULL,
    weather_label TEXT    NOT NULL,
    rationale     TEXT
);
CREATE INDEX IF NOT EXISTS idx_state_ts ON state_snapshots(ts DESC);

CREATE TABLE IF NOT EXISTS timeline_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL DEFAULT (datetime('now')),
    kind         TEXT    NOT NULL CHECK (kind IN ('milestone','phase','event')),
    title        TEXT    NOT NULL,
    description  TEXT,
    tags         TEXT                              -- comma-separated
);
CREATE INDEX IF NOT EXISTS idx_timeline_ts ON timeline_events(ts DESC);

CREATE TABLE IF NOT EXISTS semantic_memory (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    key           TEXT    NOT NULL UNIQUE,
    value         TEXT    NOT NULL,
    confidence    REAL    NOT NULL DEFAULT 0.5,
    last_updated  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS episodic_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL DEFAULT (datetime('now')),
    content     TEXT    NOT NULL,
    source      TEXT    NOT NULL,                 -- checkin / reflection / git / cli / ...
    embedding   BLOB
);
CREATE INDEX IF NOT EXISTS idx_episodic_ts ON episodic_memory(ts DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS episodic_memory_fts
USING fts5(content, source UNINDEXED, content='episodic_memory', content_rowid='id');

CREATE TRIGGER IF NOT EXISTS episodic_memory_ai AFTER INSERT ON episodic_memory BEGIN
    INSERT INTO episodic_memory_fts(rowid, content, source)
    VALUES (new.id, new.content, new.source);
END;
CREATE TRIGGER IF NOT EXISTS episodic_memory_ad AFTER DELETE ON episodic_memory BEGIN
    INSERT INTO episodic_memory_fts(episodic_memory_fts, rowid, content, source)
    VALUES('delete', old.id, old.content, old.source);
END;
CREATE TRIGGER IF NOT EXISTS episodic_memory_au AFTER UPDATE ON episodic_memory BEGIN
    INSERT INTO episodic_memory_fts(episodic_memory_fts, rowid, content, source)
    VALUES('delete', old.id, old.content, old.source);
    INSERT INTO episodic_memory_fts(rowid, content, source)
    VALUES (new.id, new.content, new.source);
END;

CREATE TABLE IF NOT EXISTS git_activity (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT    NOT NULL DEFAULT (datetime('now')),
    repo           TEXT    NOT NULL,
    commit_count   INTEGER NOT NULL DEFAULT 0,
    project_count  INTEGER NOT NULL DEFAULT 0,
    switch_score   REAL    NOT NULL DEFAULT 0.0,
    window_days    INTEGER NOT NULL DEFAULT 14
);
CREATE INDEX IF NOT EXISTS idx_git_ts ON git_activity(ts DESC);

-- Notes activity (Obsidian / Markdown directory).
-- Captures the input/output ratio signal: how much you read/highlight/collect
-- versus how much you actually finish writing.
CREATE TABLE IF NOT EXISTS notes_activity (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL DEFAULT (datetime('now')),
    root            TEXT    NOT NULL,
    file_count      INTEGER NOT NULL DEFAULT 0,
    new_file_count  INTEGER NOT NULL DEFAULT 0,
    edited_count    INTEGER NOT NULL DEFAULT 0,
    total_words     INTEGER NOT NULL DEFAULT 0,
    new_words       INTEGER NOT NULL DEFAULT 0,
    avg_words       REAL    NOT NULL DEFAULT 0.0,
    top_topics      TEXT,
    window_days     INTEGER NOT NULL DEFAULT 14
);
CREATE INDEX IF NOT EXISTS idx_notes_ts ON notes_activity(ts DESC);

-- Short-term event log (high-frequency, source of truth for the session).
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
    type        TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    tags        TEXT,
    session_id  TEXT    NOT NULL DEFAULT 'default'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_session_ts ON events(session_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);

-- Workspace behavior sensor (directory activity / fragmentation).
CREATE TABLE IF NOT EXISTS workspace_activity (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                   TEXT    NOT NULL DEFAULT (datetime('now')),
    root                 TEXT    NOT NULL,
    active_project_count INTEGER NOT NULL DEFAULT 0,
    touched_paths        INTEGER NOT NULL DEFAULT 0,
    fragmentation_score  REAL    NOT NULL DEFAULT 0.0,
    top_dirs             TEXT,
    window_days          INTEGER NOT NULL DEFAULT 7
);
CREATE INDEX IF NOT EXISTS idx_workspace_ts ON workspace_activity(ts DESC);

-- Weak interpretations produced from deterministic sensor rows.
-- They are questions for the user until confirmed or seen repeatedly.
CREATE TABLE IF NOT EXISTS sensor_hypotheses (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    last_seen_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    source_type      TEXT    NOT NULL CHECK (source_type IN ('git','notes','workspace','patterns')),
    source_record_id INTEGER,
    key              TEXT    NOT NULL UNIQUE,
    label            TEXT    NOT NULL,
    summary          TEXT    NOT NULL,
    evidence         TEXT,
    confidence       REAL    NOT NULL DEFAULT 0.2,
    seen_count       INTEGER NOT NULL DEFAULT 1,
    status           TEXT    NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending','confirmed','rejected','superseded')),
    user_feedback    TEXT CHECK (user_feedback IN ('confirmed','rejected') OR user_feedback IS NULL),
    user_rating      TEXT CHECK (user_rating IN ('accurate','unsure','inaccurate') OR user_rating IS NULL),
    confirmed_at     TEXT,
    rejected_at      TEXT,
    rated_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_sensor_hypotheses_status ON sensor_hypotheses(status, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_sensor_hypotheses_source ON sensor_hypotheses(source_type, last_seen_at DESC);

-- Dev review agent run persistence.
CREATE TABLE IF NOT EXISTS agent_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type     TEXT    NOT NULL CHECK (run_type IN ('dev_review')),
    status       TEXT    NOT NULL DEFAULT 'running'
                         CHECK (status IN ('running','success','partial','failed')),
    started_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at  TEXT,
    input_json   TEXT    NOT NULL DEFAULT '{}',
    steps_json   TEXT    NOT NULL DEFAULT '[]',
    error        TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_type_started ON agent_runs(run_type, started_at DESC);

CREATE TABLE IF NOT EXISTS dev_reviews (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                INTEGER NOT NULL REFERENCES agent_runs(id),
    window_days           INTEGER NOT NULL DEFAULT 7,
    summary               TEXT    NOT NULL,
    dev_weather           TEXT    NOT NULL
                                  CHECK (dev_weather IN ('Deep Work','Shipping','Collaboration Heavy','Fragmented','Blocked')),
    main_work_threads_json TEXT   NOT NULL DEFAULT '[]',
    shipping_progress_json TEXT   NOT NULL DEFAULT '[]',
    collaboration_load_json TEXT  NOT NULL DEFAULT '[]',
    meeting_load_json      TEXT   NOT NULL DEFAULT '[]',
    rhythm_risks_json      TEXT   NOT NULL DEFAULT '[]',
    next_week_suggestion  TEXT    NOT NULL,
    source_coverage_json   TEXT   NOT NULL DEFAULT '{}',
    created_at            TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_dev_reviews_created ON dev_reviews(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dev_reviews_run ON dev_reviews(run_id);
"""

_MIGRATIONS = [
    "ALTER TABLE sensor_hypotheses ADD COLUMN user_rating TEXT",
    "ALTER TABLE sensor_hypotheses ADD COLUMN rated_at TEXT",
]

_DEV_REVIEW_CURRENT_COLUMNS = {
    "main_work_threads_json",
    "shipping_progress_json",
    "collaboration_load_json",
    "meeting_load_json",
    "rhythm_risks_json",
    "source_coverage_json",
}
_DEV_REVIEW_LEGACY_COLUMNS = {
    "main_work_threads",
    "shipping_progress",
    "collaboration_load",
    "meeting_load",
    "rhythm_risks",
    "source_coverage",
}


_DB_PATH_OVERRIDE: Optional[str] = None
_LOCK = threading.Lock()


def set_db_path(path: str) -> None:
    """Override the active DB path (mainly for tests)."""
    global _DB_PATH_OVERRIDE
    _DB_PATH_OVERRIDE = path


def _resolve_db_path(db_path: Optional[str] = None) -> str:
    if db_path is not None:
        return db_path
    if _DB_PATH_OVERRIDE is not None:
        return _DB_PATH_OVERRIDE
    return get_settings().db_path


def init_db(db_path: Optional[str] = None) -> None:
    """Create tables, indexes, FTS5 mirror, and triggers if absent."""
    path = _resolve_db_path(db_path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, sqlite3.connect(path) as conn:
        conn.executescript("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")
        conn.executescript(_SCHEMA)
        _migrate_dev_reviews_json_columns(conn)
        for stmt in _MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        conn.commit()


def _migrate_dev_reviews_json_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(dev_reviews)").fetchall()
    }
    if _DEV_REVIEW_CURRENT_COLUMNS.issubset(columns):
        return
    if not _DEV_REVIEW_LEGACY_COLUMNS.issubset(columns):
        return

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dev_reviews_migrated (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id                 INTEGER NOT NULL REFERENCES agent_runs(id),
            window_days            INTEGER NOT NULL DEFAULT 7,
            summary                TEXT    NOT NULL,
            dev_weather            TEXT    NOT NULL
                                   CHECK (dev_weather IN ('Deep Work','Shipping','Collaboration Heavy','Fragmented','Blocked')),
            main_work_threads_json TEXT    NOT NULL DEFAULT '[]',
            shipping_progress_json TEXT    NOT NULL DEFAULT '[]',
            collaboration_load_json TEXT   NOT NULL DEFAULT '[]',
            meeting_load_json      TEXT    NOT NULL DEFAULT '[]',
            rhythm_risks_json      TEXT    NOT NULL DEFAULT '[]',
            next_week_suggestion   TEXT    NOT NULL,
            source_coverage_json   TEXT    NOT NULL DEFAULT '{}',
            created_at             TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        INSERT INTO dev_reviews_migrated (
            id,
            run_id,
            window_days,
            summary,
            dev_weather,
            main_work_threads_json,
            shipping_progress_json,
            collaboration_load_json,
            meeting_load_json,
            rhythm_risks_json,
            next_week_suggestion,
            source_coverage_json,
            created_at
        )
        SELECT
            id,
            run_id,
            window_days,
            summary,
            dev_weather,
            main_work_threads,
            shipping_progress,
            collaboration_load,
            meeting_load,
            rhythm_risks,
            next_week_suggestion,
            source_coverage,
            created_at
        FROM dev_reviews;

        DROP TABLE dev_reviews;
        ALTER TABLE dev_reviews_migrated RENAME TO dev_reviews;
        CREATE INDEX IF NOT EXISTS idx_dev_reviews_created ON dev_reviews(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_dev_reviews_run ON dev_reviews(run_id);
        """
    )


@contextmanager
def get_conn(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Context-managed SQLite connection with row factory."""
    path = _resolve_db_path(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = ["init_db", "get_conn", "set_db_path"]
