"""Episodic ingest (check-in + reflection) — no LLM judgment, embeddings only."""

from __future__ import annotations

import logging
from typing import Optional

from app.core.llm import LLMClient
from app.memory import episodic
from app.memory.schemas import CheckinRecord, ReflectionRecord

logger = logging.getLogger(__name__)


def format_checkin(c: CheckinRecord) -> str:
    parts = []
    if c.status:
        parts.append(f"status: {c.status}")
    if c.did_today:
        parts.append(f"did: {c.did_today}")
    if c.stuck_on:
        parts.append(f"stuck: {c.stuck_on}")
    if c.anxiety:
        parts.append(f"anxiety: {c.anxiety}")
    if c.raw:
        parts.append(f"raw: {c.raw}")
    return f"[{c.date}] " + " | ".join(parts)


class MemoryWriter:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def _safe_embed(self, text: str) -> Optional[list[float]]:
        try:
            vecs = await self._llm.embed([text])
            return vecs[0] if vecs else None
        except Exception:
            logger.exception("embedding request failed")
            return None

    async def ingest_checkin(self, checkin: CheckinRecord) -> int:
        body = format_checkin(checkin)
        embedding = await self._safe_embed(body)
        return episodic.add(content=body, source="checkin", embedding=embedding)

    async def ingest_reflection(self, reflection: ReflectionRecord) -> int:
        embedding = await self._safe_embed(reflection.content)
        return episodic.add(
            content=reflection.content,
            source=f"reflection:{reflection.kind}",
            embedding=embedding,
        )


__all__ = ["MemoryWriter", "format_checkin"]
