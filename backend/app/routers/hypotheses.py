"""T3 校准 + 主页堆查询."""

from __future__ import annotations

import asyncio
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.memory import event_log, hypotheses_view
from app.memory.derivations import run_derivations
from app.memory.schemas import FeedbackVerdict, HypothesisFeedbackPayload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hypotheses", tags=["hypotheses"])


class FeedbackIn(BaseModel):
    verdict: FeedbackVerdict


class FeedbackOut(BaseModel):
    feedback_id: str
    hypothesis_id: str
    verdict: FeedbackVerdict


@router.get("", response_model=List[dict])
def list_cards(limit: int = Query(default=3, ge=1, le=10)) -> List[dict]:
    """Return up to N active hypothesis cards (main-page stack)."""
    return hypotheses_view.card_stack(limit=limit)


@router.get("/history", response_model=List[dict])
def list_history(limit: int = Query(default=50, ge=1, le=200)) -> List[dict]:
    return hypotheses_view.card_history(limit=limit)


@router.get("/{hypothesis_id}", response_model=dict)
def get_hypothesis(hypothesis_id: str) -> dict:
    rec = event_log.get(hypothesis_id)
    if rec is None or rec.type != "hypothesis":
        raise HTTPException(status_code=404, detail="Hypothesis not found.")
    return {"id": rec.id, "timestamp": rec.timestamp, **rec.payload}


@router.post("/{hypothesis_id}/feedback", response_model=FeedbackOut)
async def submit_feedback(hypothesis_id: str, body: FeedbackIn) -> FeedbackOut:
    rec = event_log.get(hypothesis_id)
    if rec is None or rec.type != "hypothesis":
        raise HTTPException(status_code=404, detail="Hypothesis not found.")
    payload = HypothesisFeedbackPayload(hypothesis_id=hypothesis_id, verdict=body.verdict)
    fb_id = event_log.append(
        type="hypothesis_feedback",
        payload=payload.model_dump(),
        refs={"target": hypothesis_id},
    )
    # §5.3 — calibration never generates a new hypothesis; just fan out
    # derivations async (a confirmed hypothesis now becomes projectable → mem0).
    asyncio.create_task(run_derivations())
    return FeedbackOut(feedback_id=fb_id, hypothesis_id=hypothesis_id, verdict=body.verdict)
