"""Vector store abstraction.

Two implementations:
- ``SqliteVectorStore`` (default) — stores embeddings as BLOB in
  ``episodic_memory.embedding``; runs brute-force cosine similarity in numpy.
  Plenty fast for "small but deep" personal use.
- ``QdrantVectorStore`` — reserved skeleton for when local data outgrows
  SQLite. Methods raise NotImplementedError; the API is identical so swapping
  it in does not require touching agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol, Sequence

import numpy as np

from app.memory import episodic


@dataclass
class VectorHit:
    id: int
    ts: str
    content: str
    source: str
    score: float


class VectorStore(Protocol):
    def upsert(self, content: str, source: str, embedding: Sequence[float]) -> int: ...

    def search(
        self,
        embedding: Sequence[float],
        *,
        top_k: int = 5,
        source: str | None = None,
    ) -> List[VectorHit]: ...


# ---------------------------------------------------------------------------
class SqliteVectorStore:
    """Default MVP vector store: SQLite BLOB + numpy cosine similarity."""

    def upsert(self, content: str, source: str, embedding: Sequence[float]) -> int:
        return episodic.add(content=content, source=source, embedding=embedding)

    def search(
        self,
        embedding: Sequence[float],
        *,
        top_k: int = 5,
        source: str | None = None,
    ) -> List[VectorHit]:
        rows = episodic.all_with_embeddings(limit=2000)
        if not rows:
            return []

        query = np.asarray(embedding, dtype=np.float32)
        q_norm = float(np.linalg.norm(query)) or 1.0

        scored: list[VectorHit] = []
        for rid, ts, content, src, vec in rows:
            if source and src != source:
                continue
            denom = (np.linalg.norm(vec) or 1.0) * q_norm
            score = float(np.dot(vec, query) / denom)
            scored.append(VectorHit(id=rid, ts=ts, content=content, source=src, score=score))

        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]


# ---------------------------------------------------------------------------
class QdrantVectorStore:
    """RESERVED. Filling this in must not require any change to callers."""

    def __init__(self, url: str, collection: str = "weatherflow") -> None:  # pragma: no cover
        self._url = url
        self._collection = collection

    def upsert(self, content: str, source: str, embedding: Sequence[float]) -> int:  # pragma: no cover
        raise NotImplementedError("QdrantVectorStore is reserved for a future iteration")

    def search(
        self,
        embedding: Sequence[float],
        *,
        top_k: int = 5,
        source: str | None = None,
    ) -> List[VectorHit]:  # pragma: no cover
        raise NotImplementedError("QdrantVectorStore is reserved for a future iteration")


def default_store() -> VectorStore:
    return SqliteVectorStore()


__all__ = ["VectorHit", "VectorStore", "SqliteVectorStore", "QdrantVectorStore", "default_store"]
