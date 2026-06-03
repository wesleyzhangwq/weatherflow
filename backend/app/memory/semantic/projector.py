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


def _store_memory(m: Any, rec: Any, uid: str) -> None:
    """Add one curated, source-linked memory verbatim.

    infer=False: store our rendered text as-is (one L1 event → one memory). No
    LLM extraction, so the source_event_id backlink stays 1:1 (ADR-004 D5).
    """
    metadata = {
        "source_event_id": rec.id,
        "event_type": rec.type,
        "timestamp": rec.timestamp,
        "user_id": uid,
    }
    m.add(_render_for_memory(rec), user_id=uid, metadata=metadata, infer=False)


def _existing_source_ids(m: Any, uid: str) -> set[str]:
    """source_event_ids already projected for this user — the idempotency guard.

    mem0 (with infer=False) does not dedup on add, so we skip any event already
    present. This makes projection idempotent across restarts and re-runs and
    keeps one L1 event ↔ one memory.
    """
    try:
        res = m.get_all(user_id=uid)
        items = res.get("results", []) if isinstance(res, dict) else (res or [])
        return {
            sid
            for it in items
            if (sid := (it.get("metadata") or {}).get("source_event_id"))
        }
    except Exception:
        return set()


async def project_event(rec: Any, user_id: Optional[str] = None) -> bool:
    """Project a single L1 event into mem0 if it passes the whitelist and is not
    already stored (dedup by source_event_id). Returns True if newly written."""
    if not _is_projectable(rec):
        return False

    uid = user_id or rec.user_id
    try:
        from mem0 import Memory

        from app.config import get_settings
        from app.memory.semantic.mem0_config import build_mem0_config

        m = Memory.from_config(build_mem0_config(get_settings()))
        if rec.id in _existing_source_ids(m, uid):
            return False  # already projected — idempotent
        _store_memory(m, rec, uid)
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
    """Batch project recent high-value L1 events into mem0. Idempotent: skips any
    event whose source_event_id is already stored. Returns count newly written.

    Shares one mem0 client + one existing-ids snapshot per user across the batch.
    """
    events = event_log.list_recent(types=list(_PROJECTABLE_TYPES), limit=50)
    candidates = [
        r for r in events if not (since and r.timestamp <= since) and _is_projectable(r)
    ]
    if not candidates:
        return 0

    try:
        from mem0 import Memory

        from app.config import get_settings
        from app.memory.semantic.mem0_config import build_mem0_config

        m = Memory.from_config(build_mem0_config(get_settings()))
    except ImportError:
        return 0
    except Exception:
        logger.exception("mem0 init failed during batch projection")
        return 0

    seen_by_uid: dict[str, set[str]] = {}
    count = 0
    for rec in candidates:
        uid = user_id or rec.user_id
        if uid not in seen_by_uid:
            seen_by_uid[uid] = _existing_source_ids(m, uid)
        if rec.id in seen_by_uid[uid]:
            continue
        try:
            _store_memory(m, rec, uid)
            seen_by_uid[uid].add(rec.id)
            count += 1
        except Exception:
            logger.exception("Failed to project event %s into mem0", rec.id)
    return count


__all__ = ["project_event", "project_high_value_events"]
