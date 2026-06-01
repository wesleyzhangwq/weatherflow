"""MemoryProjector — projects L1 high-value events into mem0 (L2.5).

Per weatherflow-architecture-v2.md §13.3, only whitelisted event types are
projected: checkin, confirmed hypothesis, executed_action, and chat_turn
containing explicit preferences.

Each projected memory carries a source_event_id backlink to the original L1 event.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.memory import event_log

logger = logging.getLogger(__name__)

# Whitelist: only these event types get projected into mem0.
_PROJECTABLE_TYPES = frozenset({"checkin", "hypothesis", "executed_action", "chat_turn"})


def _is_projectable(rec: Any) -> bool:
    """Check if an event record should be projected into semantic memory."""
    if rec.type not in _PROJECTABLE_TYPES:
        return False

    # hypothesis: only confirmed ones
    if rec.type == "hypothesis":
        # Check if there's a subsequent hypothesis_feedback with verdict=confirmed
        feedbacks = event_log.find_refs(
            ref_key="target", ref_value=rec.id, type_="hypothesis_feedback", limit=5
        )
        return any(f.payload.get("verdict") == "confirmed" for f in feedbacks)

    # chat_turn: only if it contains explicit preference signals
    if rec.type == "chat_turn":
        content = rec.payload.get("content", "").lower()
        preference_keywords = ["prefer", "喜欢", "习惯", "always", "总是", "never", "从不", "usually", "通常"]
        return any(kw in content for kw in preference_keywords)

    # checkin and executed_action are always projectable
    return True


def _render_for_memory(rec: Any) -> str:
    """Render an event into a natural language description for mem0."""
    p = rec.payload
    if rec.type == "checkin":
        parts = [f"Check-in: weather={p.get('weather')}"]
        if p.get("project"):
            parts.append(f"project={p['project']}")
        if p.get("friction_point"):
            parts.append(f"friction={p['friction_point']}")
        if p.get("free_text"):
            parts.append(f"notes={p['free_text']}")
        return "; ".join(parts)

    if rec.type == "hypothesis":
        return (
            f"Confirmed rhythm: {p.get('label')} (confidence {p.get('confidence', 0):.2f}). "
            f"{p.get('summary', '')}"
        )

    if rec.type == "executed_action":
        return f"Executed action: {p.get('tool_name')} with result"

    if rec.type == "chat_turn":
        return f"User preference from chat: {p.get('content', '')[:200]}"

    return f"{rec.type}: {json.dumps(p, ensure_ascii=False)[:200]}"


async def project_event(rec: Any, user_id: Optional[str] = None) -> bool:
    """Project a single L1 event into mem0 if it passes the whitelist.

    Returns True if projected, False if skipped.
    """
    if not _is_projectable(rec):
        return False

    uid = user_id or rec.user_id
    text = _render_for_memory(rec)

    try:
        from mem0 import Memory

        settings = __import__("app.config", fromlist=["get_settings"]).get_settings()

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
        metadata = {
            "source_event_id": rec.id,
            "event_type": rec.type,
            "timestamp": rec.timestamp,
            "user_id": uid,
        }
        m.add(text, user_id=uid, metadata=metadata)
        logger.info("Projected %s event %s into mem0", rec.type, rec.id)
        return True

    except ImportError:
        logger.debug("mem0 not installed, skipping projection")
        return False
    except Exception:
        logger.exception("Failed to project event %s into mem0", rec.id)
        return False


async def project_high_value_events(
    since: Optional[str] = None,
    user_id: Optional[str] = None,
) -> int:
    """Batch project recent high-value L1 events into mem0.

    Called after hypothesis generation or DMW run.
    Returns count of events projected.
    """
    # Fetch recent events of projectable types
    types_list = list(_PROJECTABLE_TYPES)
    events = event_log.list_recent(types=types_list, limit=50)

    count = 0
    for rec in events:
        if since and rec.timestamp <= since:
            continue
        if await project_event(rec, user_id=user_id):
            count += 1

    return count


__all__ = ["project_event", "project_high_value_events"]
