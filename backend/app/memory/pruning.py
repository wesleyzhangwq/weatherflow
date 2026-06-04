"""Hypothesis-card cap: keep only the latest N hypotheses.

⚠️ This module physically deletes L1 rows — a deliberate deviation from the
append-only invariant, enabled per an explicit product decision (the home card
stack stores at most N hypotheses; older ones are removed). See
``event_log.delete`` and docs/DECISIONS-v2.md.

Trade-off (documented so it isn't a surprise): capping hypotheses globally
shrinks the history that DMW pattern-learning (§9.2 needs ≥3 confirmed
occurrences in 14 days) and past-rhythm semantic recall draw on. Raise
``HYPOTHESIS_KEEP_LIMIT`` to soften this.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from app.config import get_settings
from app.memory import event_log

logger = logging.getLogger(__name__)


async def prune_hypotheses(
    keep: Optional[int] = None, user_id: Optional[str] = None
) -> int:
    """Keep the latest ``keep`` hypotheses; delete older hypothesis events plus
    their feedback events and mem0 projections. Returns rows deleted from L1."""
    settings = get_settings()
    k = keep if keep is not None else settings.hypothesis_keep_limit
    uid = user_id or settings.default_user_id

    rows = event_log.list_recent(user_id=uid, types=["hypothesis"], limit=1000)
    if len(rows) <= k:
        return 0

    old_ids = [r.id for r in rows[k:]]  # rows are newest-first
    old_set = set(old_ids)

    # Cascade 1: feedback events that target a pruned hypothesis (avoid orphans).
    fb_ids: list[str] = []
    for hid in old_ids:
        fb_ids.extend(
            f.id
            for f in event_log.find_refs(
                ref_key="target", ref_value=hid, type_="hypothesis_feedback", limit=50
            )
        )

    # Cascade 2: mem0 projections backlinking to pruned hypotheses.
    await _delete_mem0_for_sources(old_set, uid)

    removed = event_log.delete(old_ids + fb_ids)
    logger.info(
        "Pruned %d hypothesis row(s) + %d feedback (kept latest %d)",
        len(old_ids), len(fb_ids), k,
    )
    return removed


async def _delete_mem0_for_sources(source_ids: Iterable[str], uid: str) -> None:
    source_set = set(source_ids)
    if not source_set:
        return
    try:
        from mem0 import Memory

        from app.memory.semantic.mem0_config import build_mem0_config

        m = Memory.from_config(build_mem0_config(get_settings()))
        res = m.get_all(user_id=uid)
        items = res.get("results", []) if isinstance(res, dict) else (res or [])
        for it in items:
            sid = (it.get("metadata") or {}).get("source_event_id")
            if sid in source_set and it.get("id"):
                try:
                    m.delete(it["id"])
                except Exception:
                    pass
    except ImportError:
        pass
    except Exception:
        logger.exception("mem0 prune (delete pruned-hypothesis memories) failed")


__all__ = ["prune_hypotheses"]
