"""Reflection endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.orchestrator import Orchestrator
from app.memory import reflection_repo
from app.memory.schemas import ReflectionKind, ReflectionRecord
from app.routers._deps import get_orchestrator

router = APIRouter(prefix="/api/reflection", tags=["reflection"])


@router.post("/run", response_model=ReflectionRecord)
async def run_reflection(
    kind: ReflectionKind = Query("daily"),
    session_id: str = Query("default"),
    orch: Orchestrator = Depends(get_orchestrator),
) -> ReflectionRecord:
    if kind == "weekly":
        result = await orch.weekly_loop(session_id=session_id)
    else:
        result = await orch.daily_loop(session_id=session_id)
    return result.reflection


@router.get("", response_model=list[ReflectionRecord])
async def list_reflections(
    limit: int = 10,
    kind: Optional[ReflectionKind] = None,
) -> list[ReflectionRecord]:
    return reflection_repo.recent(limit=limit, kind=kind)
