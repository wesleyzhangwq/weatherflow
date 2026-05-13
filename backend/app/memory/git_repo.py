"""CRUD helpers for git activity sensor signals."""

from __future__ import annotations

from typing import List

from app.memory.schemas import GitActivityIn, GitActivityRecord
from app.memory.store import get_conn


def add(payload: GitActivityIn) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO git_activity
              (repo, commit_count, project_count, switch_score, window_days)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload.repo,
                int(payload.commit_count),
                int(payload.project_count),
                float(payload.switch_score),
                int(payload.window_days),
            ),
        )
        return int(cur.lastrowid)


def recent(limit: int = 30) -> List[GitActivityRecord]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, ts, repo, commit_count, project_count, switch_score, window_days
            FROM git_activity ORDER BY ts DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [GitActivityRecord(**dict(r)) for r in rows]


__all__ = ["add", "recent"]
