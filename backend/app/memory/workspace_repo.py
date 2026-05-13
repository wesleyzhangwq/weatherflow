"""Persist workspace activity sensor rows."""

from __future__ import annotations

import json
from typing import List, Optional

from app.memory.schemas import WorkspaceActivityIn, WorkspaceActivityRecord
from app.memory.store import get_conn


def add(payload: WorkspaceActivityIn) -> int:
    top = json.dumps(payload.top_dirs, ensure_ascii=False) if payload.top_dirs else None
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO workspace_activity (
                root, active_project_count, touched_paths,
                fragmentation_score, top_dirs, window_days
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.root,
                payload.active_project_count,
                payload.touched_paths,
                payload.fragmentation_score,
                top,
                payload.window_days,
            ),
        )
        return int(cur.lastrowid)


def recent(limit: int = 30) -> List[WorkspaceActivityRecord]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, ts, root, active_project_count, touched_paths,
                   fragmentation_score, top_dirs, window_days
            FROM workspace_activity
            ORDER BY ts DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out: list[WorkspaceActivityRecord] = []
    for r in rows:
        dirs: Optional[list[str]] = None
        if r["top_dirs"]:
            try:
                dirs = json.loads(r["top_dirs"])
            except json.JSONDecodeError:
                dirs = None
        out.append(
            WorkspaceActivityRecord(
                id=r["id"],
                ts=r["ts"],
                root=r["root"],
                active_project_count=r["active_project_count"],
                touched_paths=r["touched_paths"],
                fragmentation_score=r["fragmentation_score"],
                top_dirs=dirs or [],
                window_days=r["window_days"],
            )
        )
    return out


__all__ = ["add", "recent"]
