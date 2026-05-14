"""Memory Agent — façade over writer / extractor / digest / compressor services."""

from __future__ import annotations

from typing import List, Optional

from app.agents.base import BaseAgent
from app.core.llm import LLMClient
from app.memory.compressor import LongTermCompressor
from app.memory.digests import MarkdownDigestWriter
from app.memory.extractor import MemoryExtractor
from app.memory.schemas import CheckinRecord, ReflectionRecord, SemanticItem, UserStateOut
from app.memory.writer import MemoryWriter


class MemoryAgent(BaseAgent):
    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm)
        self._writer = MemoryWriter(llm)
        self._extractor = MemoryExtractor(llm)
        self._digests = MarkdownDigestWriter(llm)
        self._compressor = LongTermCompressor(llm)

    async def ingest_checkin(self, checkin: CheckinRecord) -> int:
        return await self._writer.ingest_checkin(checkin)

    async def ingest_reflection(self, reflection: ReflectionRecord) -> int:
        return await self._writer.ingest_reflection(reflection)

    async def extract(
        self,
        *,
        recent_checkins: List[CheckinRecord],
        recent_reflections: List[ReflectionRecord],
    ) -> dict:
        return await self._extractor.extract(
            recent_checkins=recent_checkins,
            recent_reflections=recent_reflections,
        )

    async def write_daily_markdown(
        self,
        *,
        for_date: str,
        state: Optional[UserStateOut],
        reflection: ReflectionRecord,
        event_lines: Optional[List[str]] = None,
        semantic_hints: Optional[List[SemanticItem]] = None,
    ) -> None:
        await self._digests.write_daily_markdown(
            for_date=for_date,
            state=state,
            reflection=reflection,
            event_lines=event_lines,
            semantic_hints=semantic_hints,
        )

    async def compress_to_long_term(
        self,
        *,
        for_date: str,
        reflection: ReflectionRecord,
        extra_context: str = "",
    ) -> List[str]:
        return await self._compressor.compress_to_long_term(
            for_date=for_date,
            reflection=reflection,
            extra_context=extra_context,
        )

    async def refresh_profiles(self, *, top_semantic: int = 24) -> None:
        await self._digests.refresh_profiles(top_semantic=top_semantic)

    async def append_weekly_markdown(
        self,
        *,
        reflection: ReflectionRecord,
        summary_bullets: List[str],
    ) -> None:
        await self._digests.append_weekly_markdown(
            reflection=reflection,
            summary_bullets=summary_bullets,
        )


__all__ = ["MemoryAgent"]
