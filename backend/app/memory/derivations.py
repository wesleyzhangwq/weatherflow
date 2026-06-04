"""Derivation fan-out (ADR-004 D5).

After a high-value L1 write, refresh both derived layers from ONE place:
  - L2.5: project recent high-value events into mem0 (fixes G17 — projection
    was never wired into the running path).
  - L3:  run the DelayedMemoryWriter (4-gate) over profile.md.

Replaces the per-router ``_run_dmw_safely`` duplication. Fire-and-forget; an
external service being down (Qdrant/mem0) must never break the request path.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory cursor so we only project events newer than the last run. Resets on
# restart (then we re-scan the recent window once — mem0 dedupes on add).
_last_projection_ts: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


async def run_derivations() -> None:
    """Fan out L1 → mem0 (L2.5 episodic + L3-fast profile) and profile.md (L3).
    Each step is independently safe. Also enforces the hypothesis-card cap."""
    await _project_safely()
    await _consolidate_safely()
    await _dmw_safely()
    await _prune_safely()


_last_consolidation_ts: Optional[str] = None


async def _consolidate_safely() -> None:
    """L3-fast (ADR-006): merge new high-signal events into the profile collection
    via mem0 infer=True. Cursor avoids re-processing; gated + isolated."""
    global _last_consolidation_ts
    try:
        from app.config import get_settings

        if not get_settings().profile_consolidation_enabled:
            return
        from app.memory.semantic.consolidator import consolidate_recent

        count = await consolidate_recent(since=_last_consolidation_ts)
        _last_consolidation_ts = _now_iso()
        if count:
            logger.info("Consolidated %d signal(s) into L3-fast profile", count)
    except ImportError:
        pass
    except Exception:
        logger.exception("L3-fast consolidation failed")


async def _prune_safely() -> None:
    try:
        from app.memory.pruning import prune_hypotheses

        await prune_hypotheses()
    except Exception:
        logger.exception("hypothesis prune failed")


async def _project_safely() -> None:
    global _last_projection_ts
    try:
        from app.memory.semantic.projector import project_high_value_events

        count = await project_high_value_events(since=_last_projection_ts)
        _last_projection_ts = _now_iso()
        if count:
            logger.info("Projected %d high-value event(s) into mem0 (L2.5)", count)
    except ImportError:
        pass
    except Exception:
        logger.exception("mem0 projection failed")


async def _dmw_safely() -> None:
    try:
        from app.memory.delayed_writer import maybe_update

        await maybe_update()
    except ImportError:
        pass
    except Exception:
        logger.exception("DelayedMemoryWriter run failed")


__all__ = ["run_derivations"]
