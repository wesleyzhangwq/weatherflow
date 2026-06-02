"""T1 Check-in endpoint — synchronous (non-SSE) return per §10.3."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.graph.rhythm_graph import run_rhythm
from app.memory import event_log
from app.memory.schemas import CheckinPayload, HypothesisPayload
from app.observability.structured_logging import metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/checkin", tags=["checkin"])


class CheckinResponse(BaseModel):
    checkin_id: str
    hypothesis_id: str
    hypothesis: HypothesisPayload


@router.post("", response_model=CheckinResponse)
async def submit_checkin(payload: CheckinPayload) -> CheckinResponse:
    start = time.perf_counter()
    checkin_id = event_log.append(type="checkin", payload=payload.model_dump())
    # v2 (M1A.6): route through the rhythm subgraph, which falls back to the v1
    # orchestrator (generate_hypothesis) when langgraph is unavailable.
    hyp_id, hyp_dict = await run_rhythm(
        trigger_event_id=checkin_id,
        mode="checkin",
    )
    if hyp_id is None or hyp_dict is None:
        raise HTTPException(status_code=502, detail="Hypothesis generation failed.")
    metrics.observe("checkin.latency_ms", (time.perf_counter() - start) * 1000)
    metrics.increment("checkin.count")
    # §9.2 — fire DelayedMemoryWriter asynchronously (do not block response)
    asyncio.create_task(_run_dmw_safely())
    return CheckinResponse(
        checkin_id=checkin_id,
        hypothesis_id=hyp_id,
        hypothesis=HypothesisPayload.model_validate(hyp_dict),
    )


async def _run_dmw_safely() -> None:
    try:
        from app.memory.delayed_writer import maybe_update
        await maybe_update()
    except ImportError:
        # Phase 6 not yet wired up.
        pass
    except Exception:
        logger.exception("DelayedMemoryWriter run failed")
