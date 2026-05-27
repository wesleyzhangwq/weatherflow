"""L1 Event Log — single SQLite table, append-only.

See weatherflow-architecture-v1.md §4.1 for the schema and §4.3 for the
source-event-id invariant. Anything that's a 'fact' WeatherFlow knows lives
here. Working memory (L2) is derived per-request; long-term memory (L3) is the
profile.md file.

Key invariant: rows are NEVER updated or deleted. Hypothesis status changes
are expressed by writing a NEW `hypothesis_feedback` event that points back to
the original.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Optional

from ulid import ULID

from app.config import get_settings
from app.memory.schemas import EventRecord, EventType

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    payload      TEXT NOT NULL,
    refs         TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_user_type_ts ON events(user_id, type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_user_ts ON events(user_id, timestamp DESC);
"""

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
    path = _resolve_db_path(db_path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, sqlite3.connect(path) as conn:
        conn.executescript("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")
        conn.executescript(_SCHEMA)
        conn.commit()


@contextmanager
def get_conn(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = _resolve_db_path(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _make_event_id(type_: str) -> str:
    return f"evt_{type_}_{ULID()!s}"


def append(
    *,
    type: EventType,
    payload: dict[str, Any],
    user_id: Optional[str] = None,
    refs: Optional[dict[str, Any]] = None,
    timestamp: Optional[str] = None,
    event_id: Optional[str] = None,
) -> str:
    """Append a single event to L1. Returns its id."""
    eid = event_id or _make_event_id(type)
    ts = timestamp or _now_iso()
    uid = user_id or get_settings().default_user_id
    payload_json = json.dumps(payload, ensure_ascii=False)
    refs_json = json.dumps(refs or {}, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO events (id, type, user_id, timestamp, payload, refs) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (eid, type, uid, ts, payload_json, refs_json),
        )
    return eid


def get(event_id: str) -> Optional[EventRecord]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, type, user_id, timestamp, payload, refs FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
    return _row_to_record(row) if row else None


def latest_by_type(
    types: Iterable[EventType],
    *,
    user_id: Optional[str] = None,
    limit: int = 5,
) -> List[EventRecord]:
    uid = user_id or get_settings().default_user_id
    type_list = list(types)
    if not type_list:
        return []
    placeholders = ",".join("?" * len(type_list))
    sql = (
        f"SELECT id, type, user_id, timestamp, payload, refs FROM events "
        f"WHERE user_id = ? AND type IN ({placeholders}) "
        f"ORDER BY timestamp DESC LIMIT ?"
    )
    with get_conn() as conn:
        rows = conn.execute(sql, [uid, *type_list, limit]).fetchall()
    return [_row_to_record(r) for r in rows]


def latest_one(
    type_: EventType,
    *,
    user_id: Optional[str] = None,
) -> Optional[EventRecord]:
    rows = latest_by_type([type_], user_id=user_id, limit=1)
    return rows[0] if rows else None


def find_refs(
    *,
    ref_key: str,
    ref_value: str,
    type_: Optional[EventType] = None,
    user_id: Optional[str] = None,
    limit: int = 50,
) -> List[EventRecord]:
    """Find events whose `refs[ref_key]` contains `ref_value`.

    Implementation: JSON containment via LIKE — good enough for L1 sizes.
    """
    uid = user_id or get_settings().default_user_id
    needle = f'"{ref_value}"'
    sql = (
        "SELECT id, type, user_id, timestamp, payload, refs FROM events "
        "WHERE user_id = ? AND refs LIKE ?"
    )
    args: list[Any] = [uid, f"%{needle}%"]
    if type_:
        sql += " AND type = ?"
        args.append(type_)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    args.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    out: list[EventRecord] = []
    for row in rows:
        rec = _row_to_record(row)
        if rec.refs.get(ref_key) == ref_value or ref_value in (rec.refs.get(ref_key) or []):
            out.append(rec)
    return out


def list_recent(
    *,
    user_id: Optional[str] = None,
    types: Optional[Iterable[EventType]] = None,
    since_ts: Optional[str] = None,
    limit: int = 100,
) -> List[EventRecord]:
    uid = user_id or get_settings().default_user_id
    sql = "SELECT id, type, user_id, timestamp, payload, refs FROM events WHERE user_id = ?"
    args: list[Any] = [uid]
    if types:
        type_list = list(types)
        placeholders = ",".join("?" * len(type_list))
        sql += f" AND type IN ({placeholders})"
        args.extend(type_list)
    if since_ts:
        sql += " AND timestamp >= ?"
        args.append(since_ts)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    args.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_record(r) for r in rows]


def _row_to_record(row: sqlite3.Row) -> EventRecord:
    payload = json.loads(row["payload"]) if row["payload"] else {}
    refs = json.loads(row["refs"]) if row["refs"] else {}
    return EventRecord(
        id=row["id"],
        type=row["type"],
        user_id=row["user_id"],
        timestamp=row["timestamp"],
        payload=payload,
        refs=refs,
    )


__all__ = [
    "append",
    "find_refs",
    "get",
    "get_conn",
    "init_db",
    "latest_by_type",
    "latest_one",
    "list_recent",
    "set_db_path",
]
