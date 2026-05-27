"""Raw event lookup endpoint — powers UI evidence drill-down (§5.4)."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.memory import event_log

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/{event_id}", response_model=dict)
def get_event(event_id: str) -> dict:
    rec = event_log.get(event_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    return rec.model_dump()


@router.get("", response_model=List[dict])
def list_events(
    types: Optional[str] = Query(default=None, description="Comma-separated list."),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict]:
    type_filter = None
    if types:
        type_filter = [t.strip() for t in types.split(",") if t.strip()]
    rows = event_log.list_recent(types=type_filter, limit=limit)
    return [r.model_dump() for r in rows]
