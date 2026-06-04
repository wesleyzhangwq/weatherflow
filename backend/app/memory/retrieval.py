"""Retrieval strategies for the working-context bundle (ADR-004 D5).

The ContextLoader assembles an EvidenceBundle from two recall strategies over
L1 facts:

  - recall_recent  → recency (most-recent events by type, the v1 §6.1 behaviour)
  - recall_semantic → semantic relevance (L2.5 / mem0, the v2 addition)

Both feed the same bundle; the loader dedupes + budgets them. Naming them as
explicit strategies replaces the "L2 vs L2.5 layers" framing — in the bundle
they are just entries, every one carrying a source_event_id back to L1.
"""

from __future__ import annotations

from typing import Any, List, Tuple

from app.memory import event_log
from app.memory.schemas import EventRecord


def recall_recent(user_id: str) -> List[Tuple[EventRecord, bool]]:
    """Recency strategy (§6.1): recent high-signal events as (record, must_keep).

    must_keep marks entries the token-budget pass must never drop (feedback +
    raw snapshots).
    """
    out: List[Tuple[EventRecord, bool]] = []
    for rec in event_log.latest_by_type(["hypothesis"], user_id=user_id, limit=3):
        out.append((rec, False))
    for rec in event_log.latest_by_type(["hypothesis_feedback"], user_id=user_id, limit=5):
        out.append((rec, True))  # high signal, never truncate (§6.3)
    for rec in event_log.latest_by_type(["checkin"], user_id=user_id, limit=3):
        out.append((rec, False))

    cal = event_log.latest_one("calendar_snapshot", user_id=user_id)
    if cal:
        out.append((cal, True))
    gh = event_log.latest_one("github_snapshot", user_id=user_id)
    if gh:
        out.append((gh, True))
    summary = event_log.latest_one("evidence_summary", user_id=user_id)
    if summary:
        out.append((summary, False))
    return out


async def recall_semantic(
    query: str, user_id: str, limit: int
) -> List[dict[str, Any]]:
    """Semantic strategy (§13): mem0 memories most relevant to the query.

    Degrades to [] when mem0/Qdrant is unavailable — the bundle then falls back
    to pure recency (v1 behaviour).
    """
    if not query:
        return []
    try:
        from app.memory.semantic.recall import recall_relevant

        return await recall_relevant(query=query, user_id=user_id, limit=limit)
    except ImportError:
        return []
    except Exception:
        return []


async def recall_profile(query: str, user_id: str, limit: int) -> List[str]:
    """L3-fast strategy (ADR-006): consolidated profile traits relevant to the
    query (plain strings, no source). Degrades to [] when mem0 down."""
    if not query:
        return []
    try:
        from app.memory.semantic.recall import recall_profile as _recall

        return await _recall(query=query, user_id=user_id, limit=limit)
    except ImportError:
        return []
    except Exception:
        return []


__all__ = ["recall_recent", "recall_semantic", "recall_profile"]
