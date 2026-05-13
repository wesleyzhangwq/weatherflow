"""Episodic memory: short-horizon events + FTS5 search.

Embeddings live next to the row (BLOB column) so the default vector store and
the FTS index share one source of truth.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

from app.memory.schemas import EpisodicItem
from app.memory.store import get_conn


def add(content: str, source: str, embedding: Optional[Sequence[float]] = None) -> int:
    """Insert a new episodic memory; return its id."""
    blob: Optional[bytes] = None
    if embedding is not None:
        blob = np.asarray(embedding, dtype=np.float32).tobytes()

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO episodic_memory (content, source, embedding) VALUES (?, ?, ?)",
            (content, source, blob),
        )
        return int(cur.lastrowid)


def recent(limit: int = 20, source: Optional[str] = None) -> List[EpisodicItem]:
    sql = "SELECT id, ts, content, source FROM episodic_memory"
    args: list = []
    if source:
        sql += " WHERE source = ?"
        args.append(source)
    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)

    with get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [EpisodicItem(**dict(r)) for r in rows]


def fts_search(query: str, limit: int = 10) -> List[EpisodicItem]:
    """Plain FTS5 keyword search."""
    if not query.strip():
        return []
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT em.id, em.ts, em.content, em.source
            FROM episodic_memory_fts fts
            JOIN episodic_memory em ON em.id = fts.rowid
            WHERE episodic_memory_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    return [EpisodicItem(**dict(r)) for r in rows]


def all_with_embeddings(limit: int = 1000) -> list[tuple[int, str, str, str, np.ndarray]]:
    """Return rows that have an embedding, newest first.

    Returns: list of (id, ts, content, source, embedding_array).
    """
    out: list[tuple[int, str, str, str, np.ndarray]] = []
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, ts, content, source, embedding
            FROM episodic_memory
            WHERE embedding IS NOT NULL
            ORDER BY ts DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    for r in rows:
        arr = np.frombuffer(r["embedding"], dtype=np.float32)
        out.append((r["id"], r["ts"], r["content"], r["source"], arr))
    return out


def count() -> int:
    with get_conn() as conn:
        (n,) = conn.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()
    return int(n)


__all__ = ["add", "recent", "fts_search", "all_with_embeddings", "count"]
