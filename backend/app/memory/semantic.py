"""Semantic memory: long-term observations about the user (key/value)."""

from __future__ import annotations

from typing import List, Optional

from app.memory.schemas import SemanticItem
from app.memory.store import get_conn


def upsert(key: str, value: str, confidence: float = 0.5) -> None:
    """Upsert a semantic observation, blending confidence on conflict.

    Strategy: if key exists, replace value with the newer one but average
    confidence with the previous value (cheap, monotone-ish blending).
    """
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT confidence FROM semantic_memory WHERE key = ?", (key,)
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO semantic_memory (key, value, confidence) VALUES (?, ?, ?)",
                (key, value, max(0.0, min(1.0, confidence))),
            )
        else:
            blended = (float(existing["confidence"]) + max(0.0, min(1.0, confidence))) / 2.0
            conn.execute(
                """
                UPDATE semantic_memory
                SET value = ?, confidence = ?, last_updated = datetime('now')
                WHERE key = ?
                """,
                (value, blended, key),
            )


def all(limit: int = 100) -> List[SemanticItem]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT key, value, confidence, last_updated
            FROM semantic_memory
            ORDER BY confidence DESC, last_updated DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [SemanticItem(**dict(r)) for r in rows]


def get(key: str) -> Optional[SemanticItem]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT key, value, confidence, last_updated FROM semantic_memory WHERE key = ?",
            (key,),
        ).fetchone()
    return SemanticItem(**dict(row)) if row else None


__all__ = ["upsert", "all", "get"]
