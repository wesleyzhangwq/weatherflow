"""CRUD helpers for the ``reflections`` table."""

from __future__ import annotations

import json
from datetime import date as _date
from typing import List, Optional

from app.memory.schemas import ReflectionKind, ReflectionRecord
from app.memory.store import get_conn


def add(
    content: str,
    kind: ReflectionKind = "daily",
    insights: Optional[dict] = None,
    when: Optional[str] = None,
) -> int:
    when = when or _date.today().isoformat()
    insights_json = json.dumps(insights, ensure_ascii=False) if insights else None
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO reflections (date, kind, content, insights)
            VALUES (?, ?, ?, ?)
            """,
            (when, kind, content, insights_json),
        )
        return int(cur.lastrowid)


def recent(limit: int = 10, kind: Optional[ReflectionKind] = None) -> List[ReflectionRecord]:
    sql = "SELECT id, date, kind, content, insights, created_at FROM reflections"
    args: list = []
    if kind:
        sql += " WHERE kind = ?"
        args.append(kind)
    sql += " ORDER BY date DESC, id DESC LIMIT ?"
    args.append(limit)

    out: list[ReflectionRecord] = []
    with get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    for r in rows:
        d = dict(r)
        if d.get("insights"):
            try:
                d["insights"] = json.loads(d["insights"])
            except json.JSONDecodeError:
                d["insights"] = None
        out.append(ReflectionRecord(**d))
    return out


__all__ = ["add", "recent"]
