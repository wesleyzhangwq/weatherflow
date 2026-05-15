"""State Agent — maintain the user's life-state vector and weather label."""

from __future__ import annotations

import json
from typing import Any, Optional

from app.agents.base import BaseAgent
from app.core.llm import chat_json
from app.core.model_router import model_for
from app.core.prompts import STATE_SYSTEM
from app.memory import checkin_repo, hypothesis_repo, profile_md, state_repo
from app.memory.schemas import CheckinRecord, GitActivityRecord, SensorHypothesis, UserStateOut

_VALID_LABELS = {"Momentum", "Confusion", "Burnout", "Overload", "Recovery"}


def _clamp(v: Any, default: int = 50) -> int:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return default


def _heuristic_state(
    checkin: Optional[CheckinRecord],
    active_hypotheses: list[SensorHypothesis],
) -> dict:
    """Cheap deterministic baseline used when no LLM is available
    (offline tests, missing API key, fallback). Not as nuanced as the LLM
    but always available.
    """
    text = " ".join(
        filter(
            None,
            [
                (checkin.status if checkin else None),
                (checkin.did_today if checkin else None),
                (checkin.stuck_on if checkin else None),
                (checkin.anxiety if checkin else None),
                (checkin.raw if checkin else None),
            ],
        )
    ).lower()

    burnout_kw = any(
        k in text
        for k in (
            "burn",
            "burnout",
            "tired",
            "exhausted",
            "drained",
            "累",
            "疲惫",
            "耗尽",
            "没电",
            "压力",
            "焦虑",
            "失控",
        )
    )
    overload_kw = any(
        k in text
        for k in (
            "overload",
            "too much",
            "too many",
            "framework",
            "过载",
            "太多",
            "混乱",
            "信息太多",
            "有点乱",
            "分散",
        )
    )
    momentum_kw = any(
        k in text
        for k in (
            "shipped",
            "done",
            "finished",
            "完成",
            "推进",
            "发布",
            "交付",
            "收尾",
            "有动力",
            "清晰",
        )
    )
    stuck_kw = bool(checkin and (checkin.stuck_on or "").strip())

    hypothesis_text = " ".join(
        f"{h.key} {h.label} {h.summary}" for h in active_hypotheses
    ).lower()
    switching_hypothesis = "switch" in hypothesis_text or "切换" in hypothesis_text
    output_hypothesis = "output_active" in hypothesis_text or "推进" in hypothesis_text

    base = {
        "focus": 60,
        "stress": 40,
        "burnout": 30,
        "momentum": 50,
        "confidence": 55,
        "motivation": 55,
    }
    if burnout_kw:
        base["burnout"] += 30
        base["stress"] += 20
        base["momentum"] -= 20
    if overload_kw or switching_hypothesis:
        base["focus"] -= 15
        base["momentum"] -= 10
    if momentum_kw or output_hypothesis:
        base["momentum"] += 20
        base["confidence"] += 10
        base["focus"] += 5
    if stuck_kw:
        base["stress"] += 10

    state = {k: _clamp(v) for k, v in base.items()}

    if state["burnout"] >= 60:
        label = "Burnout"
    elif overload_kw or switching_hypothesis:
        label = "Overload"
    elif state["momentum"] >= 65 and state["focus"] >= 60:
        label = "Momentum"
    elif state["momentum"] >= 50 and state["burnout"] < 40:
        label = "Recovery"
    else:
        label = "Confusion"

    return {
        **state,
        "weather_label": label,
        "rationale": "（离线启发式估计，仅供参考。）",
    }


class StateAgent(BaseAgent):
    async def estimate(
        self,
        *,
        checkin: Optional[CheckinRecord] = None,
        git_recent: Optional[list[GitActivityRecord]] = None,
    ) -> UserStateOut:
        checkin = checkin or checkin_repo.latest()
        active_hypotheses = hypothesis_repo.active(limit=12)
        recent_checkins = checkin_repo.recent(limit=7)

        context = {
            "checkin": checkin.model_dump() if checkin else None,
            "recent_checkins": [c.model_dump() for c in recent_checkins],
            "profile": profile_md.read_profile(max_chars=2500),
            "active_sensor_hypotheses": [h.model_dump() for h in active_hypotheses],
        }

        try:
            raw: dict = await chat_json(
                self.llm,
                [
                    {"role": "system", "content": STATE_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            "Given the following structured context, produce the JSON described "
                            "in the system prompt. CONTEXT:\n"
                            + json.dumps(context, ensure_ascii=False, indent=2)
                        ),
                    },
                ],
                model=model_for("state"),
                temperature=0.2,
            )
        except Exception:
            raw = _heuristic_state(checkin, active_hypotheses)

        state = UserStateOut(
            focus=_clamp(raw.get("focus")),
            stress=_clamp(raw.get("stress")),
            burnout=_clamp(raw.get("burnout")),
            momentum=_clamp(raw.get("momentum")),
            confidence=_clamp(raw.get("confidence")),
            motivation=_clamp(raw.get("motivation")),
            weather_label=(
                raw.get("weather_label")
                if raw.get("weather_label") in _VALID_LABELS
                else "Confusion"
            ),
            rationale=(raw.get("rationale") or "")[:240] or None,
        )
        state_repo.add(state)
        return state


__all__ = ["StateAgent"]
