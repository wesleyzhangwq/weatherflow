"""Reflection Agent — daily and weekly reflections.

Voice: gentle, never preachy, never TODO-app.
"""

from __future__ import annotations

import json

from app.agents.base import BaseAgent
from app.core.model_router import model_for
from app.core.patterns import detect as detect_patterns
from app.core.prompts import REFLECTION_DAILY_SYSTEM, REFLECTION_WEEKLY_SYSTEM
from app.memory import (
    checkin_repo,
    hypothesis_repo,
    reflection_repo,
    state_repo,
)
from app.memory.schemas import ReflectionKind, ReflectionRecord


_FALLBACK_DAILY = (
    "Today was today. You showed up enough to write this down, and that counts. "
    "If something is stuck, it's allowed to stay stuck for now. "
    "Tomorrow can be quiet too."
)

_FALLBACK_WEEKLY = (
    "This week did not need to be impressive. "
    "Notice what kept you here, even on the dim days; that is the through-line. "
    "It might be enough, this week, to close one small loop instead of starting a new one."
)


class ReflectionAgent(BaseAgent):
    async def run(self, kind: ReflectionKind = "daily") -> ReflectionRecord:
        latest_checkin = checkin_repo.latest()
        recent_checkins = checkin_repo.recent(limit=7 if kind == "daily" else 14)
        latest_state = state_repo.latest()
        active_hypotheses = hypothesis_repo.active(limit=8)
        pending_hypotheses = hypothesis_repo.pending(limit=8)
        try:
            pattern_report = detect_patterns(
                window_days=7 if kind == "daily" else 14
            ).to_dict()
        except Exception:
            pattern_report = {"metrics": [], "patterns": []}

        context = {
            "latest_checkin": latest_checkin.model_dump() if latest_checkin else None,
            "recent_checkins": [c.model_dump() for c in recent_checkins],
            "latest_state": latest_state.model_dump() if latest_state else None,
            "active_sensor_hypotheses": [h.model_dump() for h in active_hypotheses],
            "pending_sensor_hypotheses_to_ask_about": [
                h.model_dump() for h in pending_hypotheses
            ],
            "patterns": pattern_report.get("patterns", []),
        }

        system = REFLECTION_DAILY_SYSTEM if kind == "daily" else REFLECTION_WEEKLY_SYSTEM
        user = (
            "Write the reflection. Use this structured context as background, but do NOT list it back.\n\n"
            f"CONTEXT:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
        )

        try:
            content = await self.llm.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                model=model_for("reflection"),
                temperature=0.6,
                max_tokens=400,
            )
            content = (content or "").strip()
            if not content:
                raise RuntimeError("empty reflection")
        except Exception:
            content = _FALLBACK_DAILY if kind == "daily" else _FALLBACK_WEEKLY

        insights = {
            "weather_label": latest_state.weather_label if latest_state else None,
            "checkins_considered": len(recent_checkins),
            "active_hypotheses_considered": len(active_hypotheses),
            "pending_hypotheses_available": len(pending_hypotheses),
        }
        rid = reflection_repo.add(content=content, kind=kind, insights=insights)

        return ReflectionRecord(
            id=rid,
            date=(latest_checkin.date if latest_checkin else _today()),
            kind=kind,
            content=content,
            insights=insights,
            created_at="",
        )


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


__all__ = ["ReflectionAgent"]
