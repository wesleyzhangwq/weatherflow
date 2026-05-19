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
from app.memory import checkin_repo, dev_review_repo, events_repo, profile_md, reflection_repo
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
        latest_dev_review = dev_review_repo.latest_review()
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
            "latest_dev_review": (
                {
                    "created_at": latest_dev_review.created_at,
                    "window_days": latest_dev_review.window_days,
                    "dev_weather": latest_dev_review.dev_weather,
                    "summary": latest_dev_review.summary,
                    "main_work_threads": latest_dev_review.main_work_threads,
                    "rhythm_risks": latest_dev_review.rhythm_risks,
                    "next_week_suggestion": latest_dev_review.next_week_suggestion,
                }
                if latest_dev_review
                else None
            ),
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
            "## Feedback",
            goals or "- 暂无。",
        ]
    )


def _fallback_profile(payload: dict) -> str:
    checkins = payload.get("recent_checkins") or []
    dev_review = payload.get("latest_dev_review") or {}
    latest = payload.get("latest_state") or {}
    weather = latest.get("weather_label") or "Unknown"
    dev_lines = []
    if dev_review:
        dev_lines.append(f"- 最近 Dev Review：{dev_review.get('dev_weather')}。")
        if dev_review.get("summary"):
            dev_lines.append(f"- {dev_review.get('summary')}")
    else:
        dev_lines.append("- 暂无 Dev Review，可运行一次开发节奏回顾来补充画像。")
    return "\n\n".join(
        [
            "# WeatherFlow Profile",
            "_Auto-maintained by WeatherFlow. You can edit this file directly._",
            "## Current read",
            f"- 最近已有 {len(checkins)} 条 check-in 可参考。",
            f"- 当前天气判断偏向：{weather}。",
            "## Useful patterns",
            *dev_lines,
            "## Feedback",
            "- 暂无需要单独记录的反馈。",
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
