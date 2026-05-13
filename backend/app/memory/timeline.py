"""Growth timeline — the most soulful surface of WeatherFlow.

Records milestones, phase changes, and notable events in the user's long-term
journey. Read by the dashboard and weekly reviews.
"""

from __future__ import annotations

from typing import List, Optional

from app.memory.schemas import TimelineEvent, TimelineKind
from app.memory.store import get_conn


def add(
    title: str,
    kind: TimelineKind = "event",
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> int:
    tags_str = ",".join(t.strip() for t in tags) if tags else None
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO timeline_events (kind, title, description, tags)
            VALUES (?, ?, ?, ?)
            """,
            (kind, title, description, tags_str),
        )
        return int(cur.lastrowid)


def recent(limit: int = 50) -> List[TimelineEvent]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, ts, kind, title, description, tags
            FROM timeline_events
            ORDER BY ts DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    out: list[TimelineEvent] = []
    for r in rows:
        out.append(
            TimelineEvent(
                id=r["id"],
                ts=r["ts"],
                kind=r["kind"],
                title=r["title"],
                description=r["description"],
                tags=[t for t in (r["tags"] or "").split(",") if t],
            )
        )
    return out


__all__ = ["add", "recent"]
