"""Growth timeline endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.memory import timeline as timeline_repo
from app.memory.schemas import TimelineEvent, TimelineKind

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


class TimelineCreate(BaseModel):
    title: str
    kind: TimelineKind = "event"
    description: str | None = None
    tags: list[str] = []


@router.get("", response_model=list[TimelineEvent])
async def list_timeline(limit: int = 50) -> list[TimelineEvent]:
    return timeline_repo.recent(limit=limit)


@router.post("", response_model=TimelineEvent)
async def add_timeline(body: TimelineCreate) -> TimelineEvent:
    rid = timeline_repo.add(
        title=body.title,
        kind=body.kind,
        description=body.description,
        tags=body.tags,
    )
    items = timeline_repo.recent(limit=1)
    if items and items[0].id == rid:
        return items[0]
    return TimelineEvent(
        id=rid,
        ts="",
        kind=body.kind,
        title=body.title,
        description=body.description,
        tags=body.tags,
    )
