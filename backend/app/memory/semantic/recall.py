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
        from app.memory.semantic.mem0_config import build_mem0_config

        settings = get_settings()
        uid = user_id or settings.default_user_id

        m = Memory.from_config(build_mem0_config(settings))
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
