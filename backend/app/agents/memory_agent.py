"""Memory Agent — short→mid→long compression, semantic KV, timeline."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import List, Optional

from app.agents.base import BaseAgent
from app.config import get_settings
from app.core.llm import chat_json
from app.core.model_router import model_for
from app.core.prompts import (
    MEMORY_COMPRESS_SYSTEM,
    MEMORY_EXTRACT_SYSTEM,
    PROFILE_REFRESH_SYSTEM,
)
from app.memory import episodic, events_repo, hypothesis_repo, midterm_md, semantic, timeline
from app.memory.long_term_vector import get_long_term_store
from app.memory.schemas import CheckinRecord, ReflectionRecord, SemanticItem, UserStateOut

logger = logging.getLogger(__name__)


class MemoryAgent(BaseAgent):
    async def ingest_checkin(self, checkin: CheckinRecord) -> int:
        body = _format_checkin(checkin)
        embedding = await self._safe_embed(body)
        return episodic.add(content=body, source="checkin", embedding=embedding)

    async def ingest_reflection(self, reflection: ReflectionRecord) -> int:
        embedding = await self._safe_embed(reflection.content)
        return episodic.add(
            content=reflection.content,
            source=f"reflection:{reflection.kind}",
            embedding=embedding,
        )

    async def extract(
        self,
        *,
        recent_checkins: List[CheckinRecord],
        recent_reflections: List[ReflectionRecord],
    ) -> dict:
        """Persist semantic KV + timeline milestones/phases."""
        if not recent_checkins and not recent_reflections:
            return {"semantic": [], "milestones": [], "phases": []}

        material: dict = {
            "checkins": [c.model_dump() for c in recent_checkins[-7:]],
            "reflections": [
                {"date": r.date, "kind": r.kind, "content": r.content}
                for r in recent_reflections[-5:]
            ],
        }
        suggestion_feedback = _recent_event_payloads("suggestion_feedback")
        memory_feedback = _recent_event_payloads("memory_feedback")
        if suggestion_feedback:
            material["suggestion_feedback"] = suggestion_feedback
        if memory_feedback:
            material["memory_feedback"] = memory_feedback
        active_hypotheses = hypothesis_repo.active(limit=8)
        if active_hypotheses:
            material["confirmed_or_repeated_sensor_hypotheses"] = [
                h.model_dump() for h in active_hypotheses
            ]
        try:
            data = await chat_json(
                self.llm,
                [
                    {"role": "system", "content": MEMORY_EXTRACT_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            "Recent material:\n"
                            + json.dumps(material, ensure_ascii=False, indent=2)
                        ),
                    },
                ],
                model=model_for("memory"),
                temperature=0.2,
            )
        except Exception:
            logger.exception("memory extraction failed; semantic/timeline update skipped")
            return {"semantic": [], "milestones": [], "phases": []}

        sem = data.get("semantic") or []
        miles = data.get("milestones") or []
        phases = data.get("phases") or []

        for item in sem:
            try:
                semantic.upsert(
                    key=str(item["key"]).strip().lower().replace(" ", "_")[:64],
                    value=str(item["value"]).strip(),
                    confidence=float(item.get("confidence", 0.5)),
                )
            except (KeyError, TypeError, ValueError):
                continue

        for m in miles:
            try:
                tags = m.get("tags") or []
                if not isinstance(tags, list):
                    tags = []
                timeline.add(
                    title=str(m["title"]).strip()[:120],
                    kind="milestone",
                    description=(str(m.get("description") or "")).strip()[:500] or None,
                    tags=[str(t)[:32] for t in tags][:8],
                )
            except (KeyError, TypeError):
                continue

        for p in phases:
            try:
                tags = p.get("tags") or []
                if not isinstance(tags, list):
                    tags = []
                timeline.add(
                    title=str(p["title"]).strip()[:120],
                    kind="phase",
                    description=(str(p.get("description") or "")).strip()[:500] or None,
                    tags=[str(t)[:32] for t in tags][:8],
                )
            except (KeyError, TypeError):
                continue

        return {"semantic": sem, "milestones": miles, "phases": phases}

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

    async def compress_to_long_term(
        self,
        *,
        for_date: str,
        reflection: ReflectionRecord,
        extra_context: str = "",
    ) -> List[str]:
        """Memory compression: distill markdown + reflection into vector patterns."""
        digest = midterm_md.read_daily_markdown(for_date)
        bundle = {
            "daily_markdown": digest,
            "reflection": reflection.content,
            "extra": extra_context,
        }
        try:
            data = await chat_json(
                self.llm,
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

    async def refresh_profiles(self, *, top_semantic: int = 24) -> None:
        """Rewrite profile markdown from semantic KV + recent LTM search."""
        sem = semantic.all(limit=top_semantic)
        sem_bullets = "\n".join(f"- {s.key}: {s.value}" for s in sem[:20])
        # Pull a few generic patterns via embedding of a summary query
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

        memory_feedback = _recent_event_payloads("memory_feedback")
        payload = {
            "semantic_bullets": sem_bullets,
            "patterns": pattern_lines,
            "memory_feedback": memory_feedback,
        }
        try:
            data = await chat_json(
                self.llm,
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

    # ------------------------------------------------------------------
    async def _safe_embed(self, text: str) -> Optional[list[float]]:
        try:
            vecs = await self.llm.embed([text])
            return vecs[0] if vecs else None
        except Exception:
            logger.exception("embedding request failed")
            return None


def _format_checkin(c: CheckinRecord) -> str:
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


def _recent_event_payloads(
    event_type: str,
    *,
    limit: int = 12,
    session_id: str = "default",
) -> list[dict]:
    payloads: list[dict] = []
    for e in events_repo.recent(limit=60, session_id=session_id):
        if e.type != event_type:
            continue
        try:
            payload = json.loads(e.content)
            payloads.append(payload if isinstance(payload, dict) else {"value": payload})
        except json.JSONDecodeError:
            payloads.append({"raw": (e.content or "")[:500]})
        if len(payloads) >= limit:
            break
    return payloads


__all__ = ["MemoryAgent"]
