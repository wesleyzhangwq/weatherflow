"""State endpoints — current weather + trend + pattern report."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.agents import StateAgent
from app.core.llm import LLMClient
from app.core.patterns import detect as detect_patterns
from app.memory import state_repo
from app.memory.schemas import StateTrendPoint, UserStateOut
from app.routers._deps import get_llm

router = APIRouter(prefix="/api/state", tags=["state"])


@router.get("/current", response_model=UserStateOut)
async def current_state() -> UserStateOut:
    latest = state_repo.latest()
    if latest is None:
        raise HTTPException(status_code=404, detail="no state snapshots yet")
    return latest


@router.post("/refresh", response_model=UserStateOut)
async def refresh_state(llm: LLMClient = Depends(get_llm)) -> UserStateOut:
    return await StateAgent(llm).estimate()


@router.get("/trend", response_model=list[StateTrendPoint])
async def state_trend(days: int = 14) -> list[StateTrendPoint]:
    return state_repo.trend(days=days)


@router.get("/patterns")
async def state_patterns(window_days: int = 7) -> dict:
    """Window-vs-window pattern report (deterministic; no LLM)."""
    return detect_patterns(window_days=window_days).to_dict()
