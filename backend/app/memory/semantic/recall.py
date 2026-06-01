"""Semantic recall — query mem0 for relevant historical memories.

Per weatherflow-architecture-v2.md §13.2, this module provides semantic search
over L2.5 memories, returning results with source_event_id backlinks.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def recall_relevant(
    query: str,
    user_id: Optional[str] = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search mem0 for memories semantically relevant to the query.

    Returns a list of dicts with keys: text, source_event_id, event_type, score.
    Falls back to empty list when mem0 is unavailable.
    """
    try:
        from mem0 import Memory

        from app.config import get_settings

        settings = get_settings()
        uid = user_id or settings.default_user_id

        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "host": settings.qdrant_url.replace("http://", "").split(":")[0],
                    "port": int(settings.qdrant_url.split(":")[-1]) if ":" in settings.qdrant_url.split("//")[-1] else 6333,
                    "collection_name": settings.qdrant_collection,
                },
            },
        }
        if settings.embedding_api_key:
            config["embedder"] = {
                "provider": settings.embedding_provider,
                "config": {
                    "model": settings.embedding_model,
                    "api_key": settings.embedding_api_key,
                },
            }

        m = Memory.from_config(config)
        results = m.search(query, user_id=uid, limit=limit)

        memories = []
        for item in results.get("results", results if isinstance(results, list) else []):
            metadata = item.get("metadata", {})
            memories.append({
                "text": item.get("memory", item.get("text", "")),
                "source_event_id": metadata.get("source_event_id", ""),
                "event_type": metadata.get("event_type", ""),
                "score": item.get("score", 0.0),
            })

        logger.info("Semantic recall: %d memories for user %s", len(memories), uid)
        return memories[:limit]

    except ImportError:
        logger.debug("mem0 not installed, semantic recall unavailable")
        return []
    except Exception:
        logger.exception("Semantic recall failed")
        return []


__all__ = ["recall_relevant"]
