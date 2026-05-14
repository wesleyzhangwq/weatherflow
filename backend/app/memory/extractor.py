"""Semantic KV + timeline extraction (LLM judgment)."""

from __future__ import annotations

import json
import logging
from typing import List

from app.core.llm import LLMClient, chat_json
from app.core.model_router import model_for
from app.core.prompts import MEMORY_EXTRACT_SYSTEM
from app.memory import events_repo, hypothesis_repo, semantic, timeline
from app.memory.schemas import CheckinRecord, ReflectionRecord

logger = logging.getLogger(__name__)


def recent_event_payloads(
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


class MemoryExtractor:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def extract(
        self,
        *,
        recent_checkins: List[CheckinRecord],
        recent_reflections: List[ReflectionRecord],
    ) -> dict:
        if not recent_checkins and not recent_reflections:
            return {"semantic": [], "milestones": [], "phases": []}

        material: dict = {
            "checkins": [c.model_dump() for c in recent_checkins[-7:]],
            "reflections": [
                {"date": r.date, "kind": r.kind, "content": r.content}
                for r in recent_reflections[-5:]
            ],
        }
        suggestion_feedback = recent_event_payloads("suggestion_feedback")
        memory_feedback = recent_event_payloads("memory_feedback")
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
                self._llm,
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


__all__ = ["MemoryExtractor", "recent_event_payloads"]
