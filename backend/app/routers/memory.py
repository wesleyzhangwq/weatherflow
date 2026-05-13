"""Memory introspection endpoints — make the user model visible.

WeatherFlow's success criterion is: "It really seems to understand me more
and more." That cannot stay invisible. These endpoints expose what the agent
believes about the user.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.llm import LLMClient
from app.memory import episodic, events_repo, semantic
from app.memory.context import gather_memory_context
from app.memory.schemas import EpisodicItem, EventIn, EventRecord, SemanticItem
from app.memory.session_buffer import append as buffer_append
from app.routers._deps import get_llm

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/semantic", response_model=List[SemanticItem])
async def list_semantic(limit: int = 50) -> List[SemanticItem]:
    """Long-term observations the agent currently believes about the user."""
    return semantic.all(limit=limit)


@router.get("/episodic", response_model=List[EpisodicItem])
async def list_episodic(limit: int = 30) -> List[EpisodicItem]:
    return episodic.recent(limit=limit)


@router.get("/episodic/search", response_model=List[EpisodicItem])
async def search_episodic(q: str, limit: int = 10) -> List[EpisodicItem]:
    return episodic.fts_search(q, limit=limit)


class MemoryContextIn(BaseModel):
    query: str = ""
    session_id: str = "default"


@router.post("/context")
async def memory_context(
    body: MemoryContextIn,
    llm: LLMClient = Depends(get_llm),
) -> dict[str, str]:
    """Hybrid read path: SQLite events + session buffer + Markdown + vector patterns."""
    md = await gather_memory_context(
        llm,
        query_text=body.query,
        session_id=body.session_id,
    )
    return {"markdown": md}


@router.post("/events")
async def append_event(event: EventIn) -> dict[str, str]:
    eid = events_repo.add(
        type=event.type,
        content=event.content,
        tags=event.tags or None,
        session_id=event.session_id,
    )
    buffer_append(
        event.session_id,
        {"type": event.type, "content": event.content[:1200]},
    )
    return {"id": eid}


@router.get("/events/recent", response_model=List[EventRecord])
async def recent_events(
    limit: int = 50,
    session_id: str | None = None,
) -> List[EventRecord]:
    return events_repo.recent(limit=limit, session_id=session_id)
