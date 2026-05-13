"""Long-term pattern memory — Qdrant when configured, else SQLite embeddings."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np

from app.config import Settings, get_settings
from app.memory import episodic

logger = logging.getLogger(__name__)

LTM_SOURCE = "ltm_pattern"


@dataclass
class PatternHit:
    id: str
    content: str
    score: float


class SqliteLongTermStore:
    """Fallback: store compressed patterns beside episodic rows (source=ltm_pattern)."""

    def upsert_compressed(
        self,
        text: str,
        embedding: Sequence[float],
        *,
        dedupe_threshold: float,
    ) -> bool:
        text = text.strip()
        if not text:
            return False
        rows = episodic.all_with_embeddings(limit=2500)
        if rows and embedding is not None:
            q = np.asarray(embedding, dtype=np.float32)
            qn = float(np.linalg.norm(q)) or 1.0
            best = 0.0
            for _rid, _ts, content, src, vec in rows:
                if src != LTM_SOURCE:
                    continue
                denom = (float(np.linalg.norm(vec)) or 1.0) * qn
                best = max(best, float(np.dot(vec, q) / denom))
            if best >= dedupe_threshold:
                return False
        episodic.add(content=text, source=LTM_SOURCE, embedding=list(embedding))
        return True

    def search(self, embedding: Sequence[float], *, top_k: int = 5) -> List[PatternHit]:
        rows = episodic.all_with_embeddings(limit=2500)
        if not rows or embedding is None:
            return []
        q = np.asarray(embedding, dtype=np.float32)
        qn = float(np.linalg.norm(q)) or 1.0
        scored: list[PatternHit] = []
        for rid, _ts, content, src, vec in rows:
            if src != LTM_SOURCE:
                continue
            denom = (float(np.linalg.norm(vec)) or 1.0) * qn
            score = float(np.dot(vec, q) / denom)
            scored.append(PatternHit(id=f"sqlite:{rid}", content=content, score=score))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]


class QdrantLongTermStore:
    """Qdrant collection dedicated to compressed long-term patterns."""

    def __init__(self, settings: Settings) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self._settings = settings
        self._collection = settings.qdrant_collection
        kwargs = {"url": settings.qdrant_url.strip()}
        if settings.qdrant_api_key.strip():
            kwargs["api_key"] = settings.qdrant_api_key.strip()
        self._client = QdrantClient(**kwargs)
        self._VectorParams = VectorParams
        self._Distance = Distance
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        dim = int(self._settings.embedding_dim)
        names = {c.name for c in self._client.get_collections().collections}
        if self._collection in names:
            return
        try:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=self._VectorParams(size=dim, distance=self._Distance.COSINE),
            )
        except Exception as exc:  # pragma: no cover - race / concurrent create
            logger.warning("qdrant create_collection: %s", exc)

    def _point_id(self, text: str) -> str:
        norm = " ".join(text.lower().split())[:2048]
        return str(uuid.uuid5(uuid.NAMESPACE_URL, norm))

    def upsert_compressed(
        self,
        text: str,
        embedding: Sequence[float],
        *,
        dedupe_threshold: float,
    ) -> bool:
        from qdrant_client.models import PointStruct

        text = text.strip()
        if not text:
            return False
        vec = list(float(x) for x in embedding)
        hits = self._client.search(
            collection_name=self._collection,
            query_vector=vec,
            limit=1,
        )
        if hits and float(hits[0].score) >= dedupe_threshold:
            return False
        pid = self._point_id(text)
        self._client.upsert(
            collection_name=self._collection,
            points=[
                PointStruct(
                    id=pid,
                    vector=vec,
                    payload={"content": text, "source": LTM_SOURCE},
                )
            ],
        )
        return True

    def search(self, embedding: Sequence[float], *, top_k: int = 5) -> List[PatternHit]:
        vec = list(float(x) for x in embedding)
        hits = self._client.search(
            collection_name=self._collection,
            query_vector=vec,
            limit=top_k,
        )
        out: list[PatternHit] = []
        for h in hits:
            payload = h.payload or {}
            content = str(payload.get("content") or "")
            out.append(PatternHit(id=str(h.id), content=content, score=float(h.score)))
        return out


def get_long_term_store(settings: Optional[Settings] = None):
    settings = settings or get_settings()
    if settings.qdrant_url.strip():
        try:
            return QdrantLongTermStore(settings)
        except Exception as exc:
            logger.warning("Qdrant unavailable (%s); falling back to SQLite LTM.", exc)
    return SqliteLongTermStore()


__all__ = [
    "LTM_SOURCE",
    "PatternHit",
    "SqliteLongTermStore",
    "QdrantLongTermStore",
    "get_long_term_store",
]
