"""Daily check-in endpoint — runs the full daily loop after persistence."""

from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.orchestrator import Orchestrator
from app.memory import checkin_repo
from app.memory.schemas import CheckinIn, CheckinRecord, ReflectionRecord, UserStateOut
from app.routers._deps import get_orchestrator

router = APIRouter(prefix="/api/checkin", tags=["checkin"])


class CheckinResponse(BaseModel):
    checkin: CheckinRecord
    state: UserStateOut
    reflection: ReflectionRecord
    suggestion: str
    patterns: List[dict[str, Any]] = Field(default_factory=list)
    suggestion_pattern_codes: List[str] = Field(default_factory=list)
    pattern_window_days: int = 7


@router.post("", response_model=CheckinResponse)
async def submit_checkin(
    payload: CheckinIn,
    orch: Orchestrator = Depends(get_orchestrator),
) -> CheckinResponse:
    cid = checkin_repo.add(payload)
    rows = checkin_repo.recent(limit=1)
    record = rows[0] if rows and rows[0].id == cid else checkin_repo.latest()
    assert record is not None

    result = await orch.daily_loop(checkin=record, session_id=payload.session_id)
    codes = [str(p.get("code", "")) for p in result.patterns if p.get("code")]

    return CheckinResponse(
        checkin=record,
        state=result.state,
        reflection=result.reflection,
        suggestion=result.suggestion,
        patterns=result.patterns,
        suggestion_pattern_codes=codes,
        pattern_window_days=result.pattern_window_days,
    )


@router.get("/recent", response_model=list[CheckinRecord])
async def list_recent(limit: int = 14) -> list[CheckinRecord]:
    return checkin_repo.recent(limit=limit)
