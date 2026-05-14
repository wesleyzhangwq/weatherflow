"""Mid-term markdown digests + profile refresh."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import List, Optional

from app.core.llm import LLMClient, chat_json
from app.core.model_router import model_for
from app.core.prompts import PROFILE_REFRESH_SYSTEM
from app.memory import midterm_md, semantic
from app.memory.extractor import recent_event_payloads
from app.memory.long_term_vector import get_long_term_store
from app.memory.schemas import ReflectionRecord, SemanticItem, UserStateOut

logger = logging.getLogger(__name__)


class MarkdownDigestWriter:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def _safe_embed(self, text: str) -> Optional[list[float]]:
        try:
            vecs = await self._llm.embed([text])
            return vecs[0] if vecs else None
        except Exception:
            logger.exception("embedding request failed")
            return None

    async def write_daily_markdown(
        self,
        *,
        for_date: str,
        state: Optional[UserStateOut],
        reflection: ReflectionRecord,
        event_lines: Optional[List[str]] = None,
        semantic_hints: Optional[List[SemanticItem]] = None,
    ) -> None:
        midterm_md.write_daily_summary(
            for_date=for_date,
            state=state,
            reflection=reflection,
            event_lines=event_lines,
            semantic_hints=semantic_hints,
        )

    async def append_weekly_markdown(
        self,
        *,
        reflection: ReflectionRecord,
        summary_bullets: List[str],
    ) -> None:
        iso = date.today().isocalendar()
        label = f"{iso.year}-W{iso.week:02d}"
        midterm_md.append_weekly_section(
            week_label=label,
            reflection_excerpt=reflection.content[:1200],
            summary_bullets=summary_bullets,
        )

    async def refresh_profiles(self, *, top_semantic: int = 24) -> None:
        sem = semantic.all(limit=top_semantic)
        sem_bullets = "\n".join(f"- {s.key}: {s.value}" for s in sem[:20])
        query = "behavior emotion growth burnout momentum habits"
        emb = await self._safe_embed(query)
        pattern_lines = ""
        if emb:
            try:
                hits = get_long_term_store().search(emb, top_k=8)
                pattern_lines = "\n".join(f"- {h.content}" for h in hits if h.content)
            except Exception:
                logger.exception("long-term pattern search failed during profile refresh")
                pattern_lines = ""

        memory_feedback = recent_event_payloads("memory_feedback")
        payload = {
            "semantic_bullets": sem_bullets,
            "patterns": pattern_lines,
            "memory_feedback": memory_feedback,
        }
        try:
            data = await chat_json(
                self._llm,
                [
                    {"role": "system", "content": PROFILE_REFRESH_SYSTEM},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False, indent=2),
                    },
                ],
                model=model_for("memory"),
                temperature=0.35,
            )
        except Exception:
            logger.exception("profile refresh generation failed")
            return

        try:
            midterm_md.write_profile_bundle(
                user_profile_md=str(data.get("user_profile") or ""),
                behavior_md=str(data.get("behavior_patterns") or ""),
                goals_md=str(data.get("goals") or ""),
            )
        except Exception:
            logger.exception("profile markdown write failed")
            return


__all__ = ["MarkdownDigestWriter"]
