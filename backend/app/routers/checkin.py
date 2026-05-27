"""T1 Check-in endpoint — synchronous (non-SSE) return per §10.3."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.llm import LLMClient
from app.core.orchestrator import generate_hypothesis
from app.memory import event_log
from app.memory.schemas import CheckinPayload, HypothesisPayload
from app.routers._deps import get_llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/checkin", tags=["checkin"])


class CheckinResponse(BaseModel):
    checkin_id: str
    hypothesis_id: str
    hypothesis: HypothesisPayload


@router.post("", response_model=CheckinResponse)
async def submit_checkin(
    payload: CheckinPayload,
    llm: LLMClient = Depends(get_llm),
) -> CheckinResponse:
    checkin_id = event_log.append(type="checkin", payload=payload.model_dump())
    hyp_id, hyp = await generate_hypothesis(
        trigger_event_id=checkin_id,
        mode="checkin",
        llm=llm,
    )
    # §9.2 — fire DelayedMemoryWriter asynchronously (do not block response)
    asyncio.create_task(_run_dmw_safely())
    return CheckinResponse(checkin_id=checkin_id, hypothesis_id=hyp_id, hypothesis=hyp)


async def _run_dmw_safely() -> None:
    try:
        from app.memory.delayed_writer import maybe_update
        await maybe_update()
    except ImportError:
        # Phase 6 not yet wired up.
        pass
    except Exception:
        logger.exception("DelayedMemoryWriter run failed")
