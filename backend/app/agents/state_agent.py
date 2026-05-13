"""State Agent — maintain the user's life-state vector and weather label."""

from __future__ import annotations

import json
from typing import Any, Optional

from app.agents.base import BaseAgent
from app.core.llm import chat_json
from app.core.model_router import model_for
from app.core.prompts import STATE_SYSTEM
from app.memory import checkin_repo, git_repo, notes_repo, state_repo, workspace_repo
from app.memory.schemas import CheckinRecord, GitActivityRecord, UserStateOut

_VALID_LABELS = {"Momentum", "Confusion", "Burnout", "Overload", "Recovery"}


def _clamp(v: Any, default: int = 50) -> int:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return default


def _heuristic_state(
    checkin: Optional[CheckinRecord],
    git: list[GitActivityRecord],
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
        )
    )
    stuck_kw = bool(checkin and (checkin.stuck_on or "").strip())

    avg_switch = (
        sum(g.switch_score for g in git) / len(git) if git else 0.0
    )
    total_commits = sum(g.commit_count for g in git)

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
    if overload_kw or avg_switch > 0.6:
        base["focus"] -= 15
        base["momentum"] -= 10
    if momentum_kw or total_commits >= 5:
        base["momentum"] += 20
        base["confidence"] += 10
        base["focus"] += 5
    if stuck_kw:
        base["stress"] += 10

    state = {k: _clamp(v) for k, v in base.items()}

    if state["burnout"] >= 60:
        label = "Burnout"
    elif overload_kw or avg_switch > 0.6:
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
        git_recent = git_recent if git_recent is not None else git_repo.recent(limit=14)
        workspace_recent = workspace_repo.recent(limit=5)
        notes_recent = notes_repo.recent(limit=3)

        context = {
            "checkin": checkin.model_dump() if checkin else None,
            "git_recent": [g.model_dump() for g in git_recent],
            "workspace_recent": [w.model_dump() for w in workspace_recent],
            "notes_recent": [n.model_dump() for n in notes_recent],
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
            raw = _heuristic_state(checkin, git_recent)

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
