"""CRUD helpers for state snapshots."""

from __future__ import annotations

from typing import List, Optional

from app.memory.schemas import StateTrendPoint, UserStateOut
from app.memory.store import get_conn


def add(state: UserStateOut, *, ts: Optional[str] = None) -> int:
    """Insert a snapshot. If ``ts`` is None, ``datetime('now')`` is used.

    Tests / seeds can pass an explicit timestamp to make trends meaningful.
    """
    with get_conn() as conn:
        if ts is None:
            cur = conn.execute(
                """
                INSERT INTO state_snapshots
                  (focus, stress, burnout, momentum, confidence, motivation,
                   weather_label, rationale)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(state.focus),
                    int(state.stress),
                    int(state.burnout),
                    int(state.momentum),
                    int(state.confidence),
                    int(state.motivation),
                    state.weather_label,
                    state.rationale,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO state_snapshots
                  (ts, focus, stress, burnout, momentum, confidence, motivation,
                   weather_label, rationale)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    int(state.focus),
                    int(state.stress),
                    int(state.burnout),
                    int(state.momentum),
                    int(state.confidence),
                    int(state.motivation),
                    state.weather_label,
                    state.rationale,
                ),
            )
        return int(cur.lastrowid)


def latest() -> Optional[UserStateOut]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT ts, focus, stress, burnout, momentum, confidence, motivation,
                   weather_label, rationale
            FROM state_snapshots
            ORDER BY ts DESC, id DESC LIMIT 1
            """
        ).fetchone()
    return UserStateOut(**dict(row)) if row else None


def trend(days: int = 14) -> List[StateTrendPoint]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT ts, focus, stress, burnout, momentum, confidence, motivation,
                   weather_label
            FROM state_snapshots
            WHERE ts >= datetime('now', ?)
            ORDER BY ts ASC
            """,
            (f"-{int(days)} days",),
        ).fetchall()
    return [StateTrendPoint(**dict(r)) for r in rows]


__all__ = ["add", "latest", "trend"]
