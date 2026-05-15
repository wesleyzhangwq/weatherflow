"""Memory Agent — maintain one readable Markdown profile.

The lightweight loop deliberately avoids parallel long-term stores. The profile
file is the durable user model: easy to inspect, edit, and replace.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.agents.base import BaseAgent
from app.core.llm import chat_json
from app.core.model_router import model_for
from app.core.prompts import PROFILE_REFRESH_SYSTEM
from app.memory import checkin_repo, events_repo, hypothesis_repo, profile_md, reflection_repo
from app.memory.schemas import CheckinRecord, ReflectionRecord, UserStateOut

logger = logging.getLogger(__name__)


class MemoryAgent(BaseAgent):
    async def refresh_profile(
        self,
        *,
        checkin: Optional[CheckinRecord] = None,
        reflection: Optional[ReflectionRecord] = None,
        state: Optional[UserStateOut] = None,
        suggestion: str = "",
    ) -> str:
        """Refresh `profile.md` from recent user-visible material."""
        recent_checkins = checkin_repo.recent(limit=14)
        recent_reflections = reflection_repo.recent(limit=8)
        active_hypotheses = hypothesis_repo.active(limit=12)
        rated_hypotheses = hypothesis_repo.rated(limit=20)
        payload = {
            "existing_profile": profile_md.read_profile(max_chars=5000),
            "latest_checkin": checkin.model_dump() if checkin else None,
            "latest_state": state.model_dump() if state else None,
            "latest_reflection": reflection.model_dump() if reflection else None,
            "latest_suggestion": suggestion[:1000],
            "recent_checkins": [c.model_dump() for c in recent_checkins],
            "recent_reflections": [
                {"date": r.date, "kind": r.kind, "content": r.content[:1200]}
                for r in recent_reflections
            ],
            "active_hypotheses": [h.model_dump() for h in active_hypotheses],
            "hypothesis_feedback": [h.model_dump() for h in rated_hypotheses],
            "suggestion_feedback": _recent_event_payloads("suggestion_feedback"),
            "memory_feedback": _recent_event_payloads("memory_feedback"),
        }

        try:
            data = await chat_json(
                self.llm,
                [
                    {"role": "system", "content": PROFILE_REFRESH_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            "请刷新一个简洁、可手改的 WeatherFlow profile.md。"
                            "只保留长期画像，不要堆叠日志。"
                            "Return STRICT JSON with keys: user_profile, behavior_patterns, goals.\n\n"
                            + json.dumps(payload, ensure_ascii=False, indent=2)
                        ),
                    },
                ],
                model=model_for("memory"),
                temperature=0.25,
            )
            body = _profile_body_from_json(data)
        except Exception:
            logger.exception("profile refresh failed; using deterministic profile fallback")
            body = _fallback_profile(payload)

        profile_md.write_profile(body)
        return profile_md.read_profile(max_chars=8000)

    async def refresh_profiles(self, *_, **__) -> None:
        """Compatibility shim for old weekly loop/tests."""
        await self.refresh_profile()

    async def ingest_checkin(self, _checkin: CheckinRecord) -> int:
        return 0

    async def ingest_reflection(self, _reflection: ReflectionRecord) -> int:
        return 0

    async def extract(self, *_, **__) -> dict:
        return {"profile": profile_md.read_profile(max_chars=8000)}

    async def write_daily_markdown(self, *_, **__) -> None:
        return None

    async def compress_to_long_term(self, *_, **__) -> list[str]:
        return []

    async def append_weekly_markdown(self, *_, **__) -> None:
        return None


def _profile_body_from_json(data: dict) -> str:
    user_profile = str(data.get("user_profile") or "").strip()
    behavior = str(data.get("behavior_patterns") or "").strip()
    goals = str(data.get("goals") or "").strip()
    if not (user_profile or behavior or goals):
        raise ValueError("empty profile payload")
    return "\n\n".join(
        [
            "# WeatherFlow Profile",
            "_Auto-maintained by WeatherFlow. You can edit this file directly._",
            "## Current read",
            user_profile or "- 暂无稳定画像。",
            "## Useful patterns",
            behavior or "- 暂无。",
            "## Hypothesis feedback",
            goals or "- 暂无。",
        ]
    )


def _fallback_profile(payload: dict) -> str:
    checkins = payload.get("recent_checkins") or []
    active = payload.get("active_hypotheses") or []
    rated = payload.get("hypothesis_feedback") or []
    latest = payload.get("latest_state") or {}
    weather = latest.get("weather_label") or "Unknown"
    active_lines = [
        f"- {h.get('label')}: {h.get('summary')}"
        for h in active[:6]
    ] or ["- 暂无稳定模式。"]
    rated_lines = [
        f"- {h.get('user_rating')}: {h.get('label')}"
        for h in rated[:8]
    ] or ["- 暂无。"]
    return "\n\n".join(
        [
            "# WeatherFlow Profile",
            "_Auto-maintained by WeatherFlow. You can edit this file directly._",
            "## Current read",
            f"- 最近已有 {len(checkins)} 条 check-in 可参考。",
            f"- 当前天气判断偏向：{weather}。",
            "## Useful patterns",
            *active_lines,
            "## Hypothesis feedback",
            *rated_lines,
        ]
    )


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
