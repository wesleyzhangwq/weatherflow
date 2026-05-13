"""User feedback — e.g. whether the daily suggestion felt accurate."""

from __future__ import annotations

import json

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
