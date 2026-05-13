"""Append-only short-term event log (SQLite)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from app.memory.schemas import EventRecord
from app.memory.store import get_conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add(
    *,
    type: str,
    content: str,
    tags: Optional[list[str]] = None,
    session_id: str = "default",
    event_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> str:
    eid = event_id or str(uuid.uuid4())
    ts = timestamp or _now_iso()
    tags_s = json.dumps(tags, ensure_ascii=False) if tags else None
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO events (id, timestamp, type, content, tags, session_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (eid, ts, type, content, tags_s, session_id or "default"),
        )
    return eid


def recent(
    *,
    limit: int = 100,
    session_id: Optional[str] = None,
    type_prefix: Optional[str] = None,
) -> List[EventRecord]:
    clauses: list[str] = []
    args: list[Any] = []
    if session_id:
        clauses.append("session_id = ?")
        args.append(session_id)
    if type_prefix:
        clauses.append("type LIKE ?")
        args.append(f"{type_prefix}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT id, timestamp, type, content, tags, session_id
        FROM events
        {where}
        ORDER BY timestamp DESC
        LIMIT ?
    """
    args.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    out: list[EventRecord] = []
    for r in rows:
        tags: Optional[list[str]] = None
        if r["tags"]:
            try:
                tags = json.loads(r["tags"])
            except json.JSONDecodeError:
                tags = None
        out.append(
            EventRecord(
                id=r["id"],
                timestamp=r["timestamp"],
                type=r["type"],
                content=r["content"],
                tags=tags if tags is not None else [],
                session_id=r["session_id"],
            )
        )
    return out


__all__ = ["add", "recent"]
