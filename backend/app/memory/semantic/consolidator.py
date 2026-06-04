"""L3-fast: immediate profile consolidation via mem0 ``infer=True`` (ADR-006).

The projector (``semantic/projector.py``) writes the EPISODIC, source-linked
layer (``infer=False`` → ``qdrant_collection``) that feeds critic-checked
evidence. THIS module is its complement: high-signal events are merged into a
SEPARATE collection (``qdrant_profile_collection``) with ``infer=True``, so mem0
extracts durable traits and reconciles them over time. These consolidated facts
feed ``bundle.live_insights`` — never ``bundle.entries[]`` — so they bypass the
source_event_id check.

Whitelist (ADR-006 D2): user ``chat_turn`` with a preference signal, and
``hypothesis_feedback`` (confirm/reject). A confirmation enters here via the
*feedback* event (enriched with the hypothesis content), not the hypothesis
event — that is exactly when the pattern becomes user-validated. checkin /
scheduled / executed_action are NEVER consolidated (structured data must not be
LLM-paraphrased and lose precision).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import get_settings
from app.memory import event_log

logger = logging.getLogger(__name__)

_CONSOLIDATABLE = frozenset({"chat_turn", "hypothesis_feedback"})
_PREFERENCE_KEYWORDS = (
    "prefer", "喜欢", "习惯", "always", "总是", "never", "从不", "usually", "通常",
)


def _is_consolidatable(rec: Any) -> bool:
    if rec.type not in _CONSOLIDATABLE:
        return False
    if rec.type == "chat_turn":
        if rec.payload.get("role") != "user":
            return False
        content = (rec.payload.get("content") or "").lower()
        return any(kw in content for kw in _PREFERENCE_KEYWORDS)
    if rec.type == "hypothesis_feedback":
        return rec.payload.get("verdict") in ("confirmed", "rejected")
    return False


def _render_signal(rec: Any) -> str:
    """Natural-language signal mem0 can extract a durable trait from.

    confirm → corroboration; reject → counter-evidence; preference → preference.
    """
    p = rec.payload
    if rec.type == "chat_turn":
        return f"User stated a preference: {(p.get('content') or '')[:300]}"
    if rec.type == "hypothesis_feedback":
        target = p.get("hypothesis_id") or (rec.refs or {}).get("target", "")
        hyp = event_log.get(target) if target else None
        label = (hyp.payload.get("label") if hyp else None) or "a"
        summary = (hyp.payload.get("summary") if hyp else "") or ""
        if p.get("verdict") == "rejected":
            return (
                f"The user REJECTED a '{label}' rhythm read — do not treat that "
                "pattern as established for them."
            )
        return f"The user CONFIRMED they were in a '{label}' rhythm. {summary}".strip()
    return ""


def _profile_memory() -> Any:
    from mem0 import Memory

    from app.memory.semantic.mem0_config import build_mem0_config

    s = get_settings()
    return Memory.from_config(
        build_mem0_config(s, collection=s.qdrant_profile_collection)
    )


async def consolidate_event(
    rec: Any, user_id: Optional[str] = None, m: Any = None
) -> bool:
    """Merge one high-signal event into the L3-fast profile (infer=True)."""
    if not _is_consolidatable(rec):
        return False
    text = _render_signal(rec)
    if not text:
        return False
    uid = user_id or rec.user_id
    try:
        mem = m or _profile_memory()
        # infer=True: mem0 extracts durable trait(s) and merges/reconciles with
        # existing memories (handles contradictions — a reject down-weights).
        mem.add(
            text,
            user_id=uid,
            infer=True,
            metadata={
                "last_event_id": rec.id,
                "event_type": rec.type,
                "timestamp": rec.timestamp,
            },
        )
        return True
    except ImportError:
        return False
    except Exception:
        logger.exception("L3-fast consolidation failed for event %s", rec.id)
        return False


async def consolidate_recent(
    since: Optional[str] = None, user_id: Optional[str] = None
) -> int:
    """Batch-consolidate recent high-signal events. Returns count processed.

    Shares one mem0 client across the batch. No source-id dedup: infer=True does
    its own reconciliation; the `since` cursor avoids re-processing old events.
    """
    events = event_log.list_recent(types=list(_CONSOLIDATABLE), limit=50)
    candidates = [
        r for r in events if not (since and r.timestamp <= since) and _is_consolidatable(r)
    ]
    if not candidates:
        return 0
    try:
        m = _profile_memory()
    except ImportError:
        return 0
    except Exception:
        logger.exception("mem0 init failed during L3-fast consolidation")
        return 0

    count = 0
    for rec in candidates:
        if await consolidate_event(rec, user_id=user_id, m=m):
            count += 1
    return count


__all__ = ["consolidate_event", "consolidate_recent"]
