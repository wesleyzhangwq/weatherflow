"""Weak sensor hypotheses that require confirmation or repetition."""

from __future__ import annotations

import json
from typing import List, Optional

from app.memory.schemas import (
    HypothesisFeedback,
    HypothesisSourceType,
    HypothesisStatus,
    SensorHypothesis,
)
from app.memory.store import get_conn


def add_or_bump(
    *,
    source_type: HypothesisSourceType,
    key: str,
    label: str,
    summary: str,
    evidence: Optional[dict] = None,
    confidence: float = 0.2,
    source_record_id: Optional[int] = None,
) -> SensorHypothesis:
    evidence_json = json.dumps(evidence or {}, ensure_ascii=False) if evidence else None
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sensor_hypotheses (
                source_type, source_record_id, key, label, summary, evidence, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                last_seen_at = datetime('now'),
                source_record_id = excluded.source_record_id,
                label = excluded.label,
                summary = excluded.summary,
                evidence = excluded.evidence,
                confidence = excluded.confidence,
                seen_count = sensor_hypotheses.seen_count + 1
            """,
            (
                source_type,
                source_record_id,
                key[:120],
                label[:160],
                summary[:500],
                evidence_json,
                max(0.0, min(1.0, float(confidence))),
            ),
        )
    item = get_by_key(key[:120])
    if item is None:
        raise RuntimeError("sensor hypothesis upsert failed")
    return item


def get_by_key(key: str) -> Optional[SensorHypothesis]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM sensor_hypotheses WHERE key = ?
            """,
            (key,),
        ).fetchone()
    return _row_to_hypothesis(row) if row else None


def recent(
    *,
    limit: int = 30,
    status: Optional[HypothesisStatus] = None,
) -> List[SensorHypothesis]:
    args: list = []
    where = ""
    if status:
        where = "WHERE status = ?"
        args.append(status)
    args.append(limit)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM sensor_hypotheses
            {where}
            ORDER BY last_seen_at DESC, id DESC
            LIMIT ?
            """,
            args,
        ).fetchall()
    return [_row_to_hypothesis(r) for r in rows]


def pending(*, limit: int = 30) -> List[SensorHypothesis]:
    return recent(limit=limit, status="pending")


def active(*, limit: int = 30, repeated_threshold: int = 2) -> List[SensorHypothesis]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM sensor_hypotheses
            WHERE status = 'confirmed'
               OR (status = 'pending' AND seen_count >= ?)
            ORDER BY
                CASE WHEN status = 'confirmed' THEN 0 ELSE 1 END,
                last_seen_at DESC,
                id DESC
            LIMIT ?
            """,
            (int(repeated_threshold), limit),
        ).fetchall()
    return [_row_to_hypothesis(r) for r in rows]


def set_feedback(hypothesis_id: int, feedback: HypothesisFeedback) -> Optional[SensorHypothesis]:
    status = "confirmed" if feedback == "confirmed" else "rejected"
    timestamp_field = "confirmed_at" if feedback == "confirmed" else "rejected_at"
    with get_conn() as conn:
        conn.execute(
            f"""
            UPDATE sensor_hypotheses
            SET status = ?, user_feedback = ?, {timestamp_field} = datetime('now')
            WHERE id = ?
            """,
            (status, feedback, hypothesis_id),
        )
        row = conn.execute(
            "SELECT * FROM sensor_hypotheses WHERE id = ?",
            (hypothesis_id,),
        ).fetchone()
    return _row_to_hypothesis(row) if row else None


def _row_to_hypothesis(row) -> SensorHypothesis:
    data = dict(row)
    if data.get("evidence"):
        try:
            data["evidence"] = json.loads(data["evidence"])
        except json.JSONDecodeError:
            data["evidence"] = None
    return SensorHypothesis(**data)


__all__ = [
    "add_or_bump",
    "get_by_key",
    "recent",
    "pending",
    "active",
    "set_feedback",
]
