"""Full orchestration loops (state + reflection + planning + queued maintenance)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.orchestrator import DailyLoopResult, Orchestrator
from app.memory.schemas import UserStateOut
from app.routers._deps import get_orchestrator

router = APIRouter(prefix="/api/loops", tags=["loops"])


class ReflectionOut(BaseModel):
    id: int
    date: str
    kind: str
    content: str
    insights: dict[str, Any] | None = None
    created_at: str


class DailyLoopResponse(BaseModel):
    state: UserStateOut
    reflection: ReflectionOut
    suggestion: str
    patterns: list[dict[str, Any]] = Field(default_factory=list)
    pattern_window_days: int = 7


def _pack(result: DailyLoopResult) -> DailyLoopResponse:
    r = result.reflection
    return DailyLoopResponse(
        state=result.state,
        reflection=ReflectionOut(
            id=r.id,
            date=r.date,
            kind=r.kind,
            content=r.content,
            insights=r.insights,
            created_at=r.created_at,
        ),
        suggestion=result.suggestion,
        patterns=result.patterns,
        pattern_window_days=result.pattern_window_days,
    )


@router.post("/daily", response_model=DailyLoopResponse)
async def run_daily_full_loop(
    session_id: str = Query("default"),
    drain_maintenance: bool = Query(
        False,
        description="If true, process queued memory jobs before returning (slower).",
    ),
    orch: Orchestrator = Depends(get_orchestrator),
) -> DailyLoopResponse:
    """Run the full daily loop without a new check-in row (evening / manual)."""
    result = await orch.daily_loop(session_id=session_id, drain_maintenance=drain_maintenance)
    return _pack(result)


@router.post("/weekly", response_model=DailyLoopResponse)
async def run_weekly_full_loop(
    session_id: str = Query("default"),
    drain_maintenance: bool = Query(False),
    orch: Orchestrator = Depends(get_orchestrator),
) -> DailyLoopResponse:
    """Run the full weekly review loop."""
    result = await orch.weekly_loop(session_id=session_id, drain_maintenance=drain_maintenance)
    return _pack(result)


__all__ = ["router"]
