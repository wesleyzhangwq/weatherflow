"""CRUD helpers for notes activity sensor signals."""

from __future__ import annotations

from typing import List

from app.memory.schemas import NotesActivityIn, NotesActivityRecord
from app.memory.store import get_conn


def add(payload: NotesActivityIn) -> int:
    topics = ",".join(t.strip() for t in payload.top_topics) if payload.top_topics else None
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO notes_activity
              (root, file_count, new_file_count, edited_count,
               total_words, new_words, avg_words, top_topics, window_days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.root,
                int(payload.file_count),
                int(payload.new_file_count),
                int(payload.edited_count),
                int(payload.total_words),
                int(payload.new_words),
                float(payload.avg_words),
                topics,
                int(payload.window_days),
            ),
        )
        return int(cur.lastrowid)


def recent(limit: int = 30) -> List[NotesActivityRecord]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, ts, root, file_count, new_file_count, edited_count,
                   total_words, new_words, avg_words, top_topics, window_days
            FROM notes_activity ORDER BY ts DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out: list[NotesActivityRecord] = []
    for r in rows:
        d = dict(r)
        topics_str = d.pop("top_topics", None) or ""
        d["top_topics"] = [t for t in topics_str.split(",") if t]
        out.append(NotesActivityRecord(**d))
    return out


__all__ = ["add", "recent"]
