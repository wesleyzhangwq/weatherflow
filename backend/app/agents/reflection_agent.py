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
    git_repo,
    notes_repo,
    reflection_repo,
    state_repo,
    workspace_repo,
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
        recent_git = git_repo.recent(limit=10)
        recent_notes = notes_repo.recent(limit=5)
        recent_workspace = workspace_repo.recent(limit=5)
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
            "recent_git": [g.model_dump() for g in recent_git],
            "recent_notes": [n.model_dump() for n in recent_notes],
            "recent_workspace": [w.model_dump() for w in recent_workspace],
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
            "git_records_considered": len(recent_git),
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
