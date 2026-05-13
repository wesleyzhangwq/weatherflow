"""User feedback — e.g. whether the daily suggestion felt accurate."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.memory import events_repo

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class SuggestionFeedbackIn(BaseModel):
    helpful: bool = Field(..., description="True if the suggestion felt on-target.")
    suggestion_text: str = ""
    pattern_codes: list[str] = Field(default_factory=list)
    reflection_id: int | None = None
    session_id: str = "default"
    note: str | None = None


MemoryFeedbackType = Literal["accurate", "inaccurate", "stale", "important"]


class MemoryFeedbackIn(BaseModel):
    semantic_key: str = Field(..., min_length=1, max_length=128)
    feedback_type: MemoryFeedbackType
    semantic_value_snapshot: str = ""
    session_id: str = "default"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.post("/suggestion")
async def suggestion_feedback(body: SuggestionFeedbackIn) -> dict[str, str]:
    payload = {
        "helpful": body.helpful,
        "suggestion_text": (body.suggestion_text or "")[:2000],
        "pattern_codes": body.pattern_codes[:16],
        "reflection_id": body.reflection_id,
        "note": (body.note or "")[:500] or None,
    }
    events_repo.add(
        type="suggestion_feedback",
        content=json.dumps(payload, ensure_ascii=False),
        session_id=body.session_id or "default",
        tags=["suggestion", "hit" if body.helpful else "miss"],
    )
    return {"status": "ok"}


@router.post("/memory")
async def memory_feedback(body: MemoryFeedbackIn) -> dict[str, str]:
    created_at = _now_iso()
    payload = {
        "semantic_key": body.semantic_key.strip()[:128],
        "feedback_type": body.feedback_type,
        "semantic_value_snapshot": (body.semantic_value_snapshot or "")[:2000],
        "created_at": created_at,
    }
    events_repo.add(
        type="memory_feedback",
        content=json.dumps(payload, ensure_ascii=False),
        session_id=body.session_id or "default",
        tags=["memory", body.feedback_type],
        timestamp=created_at,
    )
    return {"status": "ok"}
