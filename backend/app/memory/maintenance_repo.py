"""SQLite queue for deferred memory maintenance (no Redis/Celery)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from app.memory.store import get_conn

JOB_DAILY_MEMORY = "daily_memory_update"
JOB_WEEKLY_MEMORY = "weekly_memory_update"


@dataclass
class MaintenanceJob:
    id: int
    type: str
    payload: dict[str, Any]
    status: str
    attempts: int
    last_error: Optional[str]


def enqueue(job_type: str, payload: dict[str, Any]) -> int:
    body = json.dumps(payload, ensure_ascii=False)
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO maintenance_jobs (type, payload_json, status)
            VALUES (?, ?, 'pending')
            """,
            (job_type, body),
        )
        return int(cur.lastrowid)


def pending_count(*, status: str = "pending") -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM maintenance_jobs WHERE status = ?",
            (status,),
        ).fetchone()
    return int(row["c"]) if row else 0


def claim_next() -> Optional[MaintenanceJob]:
    """Atomically pick the oldest pending job and mark it running."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id FROM maintenance_jobs
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        jid = int(row["id"])
        conn.execute(
            """
            UPDATE maintenance_jobs
            SET status = 'running',
                attempts = attempts + 1,
                updated_at = datetime('now')
            WHERE id = ? AND status = 'pending'
            """,
            (jid,),
        )
        if conn.total_changes == 0:
            return None
        full = conn.execute(
            "SELECT id, type, payload_json, status, attempts, last_error FROM maintenance_jobs WHERE id = ?",
            (jid,),
        ).fetchone()
    if not full:
        return None
    d = dict(full)
    try:
        payload = json.loads(d["payload_json"])
    except json.JSONDecodeError:
        payload = {}
    return MaintenanceJob(
        id=int(d["id"]),
        type=str(d["type"]),
        payload=payload,
        status=str(d["status"]),
        attempts=int(d["attempts"]),
        last_error=d.get("last_error"),
    )


def mark_done(job_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE maintenance_jobs
            SET status = 'done', last_error = NULL, updated_at = datetime('now')
            WHERE id = ?
            """,
            (job_id,),
        )


def mark_failed(job_id: int, err: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE maintenance_jobs
            SET status = 'failed', last_error = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (err[:4000], job_id),
        )


__all__ = [
    "MaintenanceJob",
    "enqueue",
    "claim_next",
    "mark_done",
    "mark_failed",
    "pending_count",
    "JOB_DAILY_MEMORY",
    "JOB_WEEKLY_MEMORY",
]
