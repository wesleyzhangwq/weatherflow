"""Reflection Agent — daily and weekly reflections.

Voice: gentle, never preachy, never TODO-app.
"""

from __future__ import annotations

import json

from app.agents.base import BaseAgent
from app.core.model_router import model_for
from app.core.prompts import REFLECTION_DAILY_SYSTEM, REFLECTION_WEEKLY_SYSTEM
from app.memory import reflection_repo
from app.memory.schemas import (
    CheckinRecord,
    GroundingSource,
    ReflectionContext,
    ReflectionKind,
    ReflectionRecord,
    SemanticItem,
    SensorHypothesis,
    StateTrendPoint,
    UserStateOut,
)


_FALLBACK_DAILY = (
    "今天就到这里也很好。你愿意写下来，这一点本身就值得被看见。"
    "若有什么还卡着，先允许它卡一会儿也没关系。"
    "明天可以还是轻轻的，一步一步来。"
)

_FALLBACK_WEEKLY = (
    "这一周不必非要「了不起」才算数。回头看看，是什么样的线索让你愿意留下、愿意继续试，"
    "那往往就是这一周真正的主线。"
    "若能量不高，也没关系：这周也许只要把手边最小的一个闭环收好，"
    "就比再开一头新事更温柔、也更有用。"
)


class ReflectionAgent(BaseAgent):
    async def run(
        self,
        kind: ReflectionKind = "daily",
        context: ReflectionContext | None = None,
    ) -> ReflectionRecord:
        if context is None:
            raise TypeError("ReflectionAgent.run requires a ReflectionContext (orchestrator-assembled)")
        latest_checkin = context.latest_checkin
        recent_checkins = context.recent_checkins
        latest_state = context.latest_state
        recent_states = context.recent_states
        recent_semantic = context.recent_semantic
        active_hypotheses = context.active_hypotheses
        pending_hypotheses = context.pending_hypotheses
        pattern_report = context.pattern_report or {"metrics": [], "patterns": []}

        llm_context = {
            "latest_checkin": latest_checkin.model_dump() if latest_checkin else None,
            "recent_checkins": [c.model_dump() for c in recent_checkins],
            "latest_state": latest_state.model_dump() if latest_state else None,
            "recent_states": [s.model_dump() for s in recent_states],
            "recent_semantic": [s.model_dump() for s in recent_semantic],
            "active_sensor_hypotheses": [h.model_dump() for h in active_hypotheses],
            "pending_sensor_hypotheses_to_ask_about": [
                h.model_dump() for h in pending_hypotheses
            ],
            "patterns": pattern_report.get("patterns", []),
        }

        system = REFLECTION_DAILY_SYSTEM if kind == "daily" else REFLECTION_WEEKLY_SYSTEM
        user = (
            "请根据下列结构化背景写反思正文：只输出给用户的正文，不要复述或罗列原始字段，"
            "不要使用 JSON 或代码块。\n\n"
            f"背景：\n{json.dumps(llm_context, ensure_ascii=False, indent=2)}"
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
            "grounding_sources": [
                source.model_dump()
                for source in _build_grounding_sources(
                    kind=kind,
                    latest_checkin=latest_checkin,
                    latest_state=latest_state,
                    recent_states=recent_states,
                    active_hypotheses=active_hypotheses,
                    patterns=list(pattern_report.get("patterns") or []),
                    recent_semantic=recent_semantic,
                )
            ],
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


def _build_grounding_sources(
    *,
    kind: ReflectionKind,
    latest_checkin: CheckinRecord | None,
    latest_state: UserStateOut | None,
    recent_states: list[StateTrendPoint],
    active_hypotheses: list[SensorHypothesis],
    patterns: list[dict],
    recent_semantic: list[SemanticItem],
) -> list[GroundingSource]:
    sources: list[GroundingSource] = []

    if latest_checkin:
        fields = []
        if latest_checkin.status:
            fields.append("状态")
        if latest_checkin.did_today:
            fields.append("实际推进")
        if latest_checkin.stuck_on:
            fields.append("卡住点")
        if latest_checkin.anxiety:
            fields.append("担心的事")
        label = "今天的 check-in" if kind == "daily" else "最近的 check-in"
        summary = f"参考了你填写的{_join_zh(fields) or '简短签到'}，只用于把反思贴近当下。"
        sources.append(GroundingSource(type="checkin", label=label, summary=summary))

    if latest_state or recent_states:
        label = "最近 7 天状态变化" if kind == "daily" else "最近 14 天状态变化"
        state_count = len(recent_states)
        weather = f"当前状态是「{latest_state.weather_label}」" if latest_state else "结合状态快照"
        summary = f"参考了 {state_count or 1} 次状态快照，{weather}，用于判断动能、压力和恢复感。"
        sources.append(GroundingSource(type="state", label=label, summary=summary))

    for h in active_hypotheses[:4]:
        source_labels = {
            "git": "已确认的代码活动线索",
            "notes": "已确认的笔记活动线索",
            "workspace": "已确认的工作区线索",
            "patterns": "已确认的行为模式线索",
        }
        sources.append(
            GroundingSource(
                type=h.source_type,
                label=source_labels.get(h.source_type, "已确认的传感器线索"),
                summary=f"{h.label}：{h.summary}",
            )
        )

    if patterns:
        labels = [_pattern_label_zh(str(p.get("code") or p.get("label") or "")) for p in patterns[:2]]
        label_text = _join_zh([x for x in labels if x])
        summary = f"参考了 {len(patterns)} 个本周行为模式信号。"
        if label_text:
            summary = f"参考了 {len(patterns)} 个本周行为模式信号，包括{label_text}。"
        sources.append(GroundingSource(type="patterns", label="本周行为模式", summary=summary))
    else:
        sources.append(
            GroundingSource(
                type="patterns",
                label="本周行为模式",
                summary="本周暂无显著模式信号，反思主要参考当下状态和近期记录。",
            )
        )

    if recent_semantic:
        summary = f"参考了 {len(recent_semantic)} 条长期印象，用来校准持续偏好和重复模式。"
        sources.append(GroundingSource(type="memory", label="最近长期记忆", summary=summary))

    return sources


def _join_zh(items: list[str]) -> str:
    clean = [item for item in items if item]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    return "、".join(clean[:-1]) + "和" + clean[-1]


def _pattern_label_zh(code: str) -> str:
    labels = {
        "input_up_output_down": "输入变多但输出放缓",
        "project_switching_up": "项目切换增多",
        "burnout_climbing": "倦怠感上升",
        "momentum_recovering": "动能正在恢复",
        "steady_output": "输出节奏稳定",
    }
    return labels.get(code, "")


__all__ = ["ReflectionAgent"]
