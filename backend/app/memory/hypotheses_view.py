"""Hypothesis card-stack derivation (ADR D15).

The card stack is a *computed* view over the append-only L1 log. It is NEVER
stored. Status is derived from the existence (or not) of a corresponding
hypothesis_feedback event, and from the position in the recent-active list.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from app.config import get_settings
from app.memory import event_log
from app.memory.schemas import EventRecord

CardStatus = Literal["active", "confirmed", "rejected", "partial", "expired"]


def _hypothesis_status_map(user_id: str) -> Dict[str, CardStatus]:
    """For each hypothesis event id, derive its status from L1."""
    feedback_events = event_log.list_recent(
        user_id=user_id,
        types=["hypothesis_feedback"],
        limit=500,
    )
    status: Dict[str, CardStatus] = {}
    # Iterate oldest-first so the latest feedback wins.
    for fb in reversed(feedback_events):
        target = fb.payload.get("hypothesis_id")
        if not target:
            continue
        verdict = fb.payload.get("verdict")
        if verdict in ("confirmed", "rejected", "partial"):
            status[target] = verdict
    return status


def card_stack(user_id: Optional[str] = None, *, limit: int = 3) -> List[dict]:
    """Return up to `limit` active hypotheses for the main page.

    Rules (§5.5 + ADR D15):
    - Filter out any hypothesis that has feedback (confirmed/rejected/partial)
    - For source_tag='chat', keep only the latest one per conversation_id
    - Sort by timestamp desc, take top N
    """
    uid = user_id or get_settings().default_user_id
    status_map = _hypothesis_status_map(uid)
    all_hyps = event_log.list_recent(
        user_id=uid, types=["hypothesis"], limit=200
    )

    # Drop ones with explicit feedback
    candidates: list[EventRecord] = [h for h in all_hyps if h.id not in status_map]

    # Collapse chat hypotheses by conversation_id
    seen_chat_conv: set[str] = set()
    chat_keep: list[EventRecord] = []
    others: list[EventRecord] = []
    for h in candidates:
        p = h.payload
        if p.get("source_tag") == "chat":
            cid = p.get("conversation_id")
            if not cid:
                others.append(h)
                continue
            if cid in seen_chat_conv:
                continue
            seen_chat_conv.add(cid)
            chat_keep.append(h)
        else:
            others.append(h)

    merged = sorted(chat_keep + others, key=lambda r: r.timestamp, reverse=True)
    top = merged[:limit]

    return [_render_card(h, status="active") for h in top]


def card_history(user_id: Optional[str] = None, *, limit: int = 50) -> List[dict]:
    """Full timeline of hypotheses with their derived status."""
    uid = user_id or get_settings().default_user_id
    status_map = _hypothesis_status_map(uid)
    rows = event_log.list_recent(user_id=uid, types=["hypothesis"], limit=limit)
    return [_render_card(h, status=status_map.get(h.id, "active")) for h in rows]


def _render_card(rec: EventRecord, *, status: CardStatus) -> dict:
    p = rec.payload
    return {
        "id": rec.id,
        "timestamp": rec.timestamp,
        "label": p.get("label"),
        "confidence": p.get("confidence"),
        "summary": p.get("summary"),
        "evidence": p.get("evidence") or [],
        "counter_evidence": p.get("counter_evidence") or [],
        "missing_evidence": p.get("missing_evidence") or [],
        "source_tag": p.get("source_tag"),
        "conversation_id": p.get("conversation_id"),
        "status": status,
    }


__all__ = ["CardStatus", "card_stack", "card_history"]
