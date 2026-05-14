"""CRUD helpers for the ``checkins`` table."""

from __future__ import annotations

from datetime import date as _date
from typing import List, Optional

from app.memory.schemas import CheckinIn, CheckinRecord
from app.memory.store import get_conn


def add(payload: CheckinIn, when: Optional[str] = None) -> int:
    when = when or _date.today().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO checkins (date, status, did_today, stuck_on, anxiety, raw)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                when,
                payload.status,
                payload.did_today,
                payload.stuck_on,
                payload.anxiety,
                payload.raw,
            ),
        )
        return int(cur.lastrowid)


def recent(limit: int = 14) -> List[CheckinRecord]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, date, status, did_today, stuck_on, anxiety, raw, created_at
            FROM checkins ORDER BY date DESC, id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [CheckinRecord(**dict(r)) for r in rows]


def latest() -> Optional[CheckinRecord]:
    items = recent(limit=1)
    return items[0] if items else None


def get_by_id(cid: int) -> Optional[CheckinRecord]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, date, status, did_today, stuck_on, anxiety, raw, created_at
            FROM checkins WHERE id = ?
            """,
            (cid,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d.setdefault("session_id", "default")
    return CheckinRecord(**d)


__all__ = ["add", "recent", "latest", "get_by_id"]
