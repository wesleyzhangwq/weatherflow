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
    """Fan out L1 → mem0 (L2.5) and profile.md (L3). Both independently safe."""
    await _project_safely()
    await _dmw_safely()


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
