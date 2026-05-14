"""Long-term vector compression from daily markdown + reflection."""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from app.config import get_settings
from app.core.llm import LLMClient, chat_json
from app.core.model_router import model_for
from app.core.prompts import MEMORY_COMPRESS_SYSTEM
from app.memory import midterm_md
from app.memory.long_term_vector import get_long_term_store
from app.memory.schemas import ReflectionRecord

logger = logging.getLogger(__name__)


class LongTermCompressor:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def _safe_embed(self, text: str) -> Optional[list[float]]:
        try:
            vecs = await self._llm.embed([text])
            return vecs[0] if vecs else None
        except Exception:
            logger.exception("embedding request failed")
            return None

    async def compress_to_long_term(
        self,
        *,
        for_date: str,
        reflection: ReflectionRecord,
        extra_context: str = "",
    ) -> List[str]:
        digest = midterm_md.read_daily_markdown(for_date)
        bundle = {
            "daily_markdown": digest,
            "reflection": reflection.content,
            "extra": extra_context,
        }
        try:
            data = await chat_json(
                self._llm,
                [
                    {"role": "system", "content": MEMORY_COMPRESS_SYSTEM},
                    {
                        "role": "user",
                        "content": json.dumps(bundle, ensure_ascii=False, indent=2),
                    },
                ],
                model=model_for("memory"),
                temperature=0.15,
            )
        except Exception:
            logger.exception("long-term memory compression failed")
            return []

        patterns = data.get("patterns") or []
        settings = get_settings()
        store = get_long_term_store(settings)
        inserted: list[str] = []
        for raw in patterns:
            line = str(raw).strip()
            if len(line) < 8:
                continue
            emb = await self._safe_embed(line)
            if not emb:
                continue
            try:
                if store.upsert_compressed(
                    line,
                    emb,
                    dedupe_threshold=settings.ltm_dedupe_threshold,
                ):
                    inserted.append(line)
            except Exception:
                logger.exception("long-term pattern upsert failed")
                continue
        return inserted


__all__ = ["LongTermCompressor"]
