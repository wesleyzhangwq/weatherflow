"""SQLite schema and connection helpers."""

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
    date        TEXT    NOT NULL,
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
    insights    TEXT,
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

_MIGRATIONS: list[str] = []

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

    conn.execute("DROP TABLE IF EXISTS dev_reviews_migrated")
    conn.commit()

    try:
        conn.execute("BEGIN")
        conn.execute(
            """
            CREATE TABLE dev_reviews_migrated (
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
            )
            """
        )
        conn.execute(
            """
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
            FROM dev_reviews
            """
        )
        conn.execute("DROP TABLE dev_reviews")
        conn.execute("ALTER TABLE dev_reviews_migrated RENAME TO dev_reviews")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dev_reviews_created ON dev_reviews(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dev_reviews_run ON dev_reviews(run_id)")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


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
