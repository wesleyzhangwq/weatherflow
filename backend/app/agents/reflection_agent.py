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
    semantic,
    state_repo,
    workspace_repo,
)
from app.memory.schemas import (
    CheckinRecord,
    GitActivityRecord,
    GroundingSource,
    NotesActivityRecord,
    ReflectionKind,
    ReflectionRecord,
    SemanticItem,
    StateTrendPoint,
    UserStateOut,
    WorkspaceActivityRecord,
)


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
        recent_states = state_repo.trend(days=7 if kind == "daily" else 14)
        recent_git = git_repo.recent(limit=10)
        recent_notes = notes_repo.recent(limit=5)
        recent_workspace = workspace_repo.recent(limit=5)
        recent_semantic = semantic.all(limit=6)
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
            "recent_states": [s.model_dump() for s in recent_states],
            "recent_git": [g.model_dump() for g in recent_git],
            "recent_notes": [n.model_dump() for n in recent_notes],
            "recent_workspace": [w.model_dump() for w in recent_workspace],
            "recent_semantic": [s.model_dump() for s in recent_semantic],
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
            "grounding_sources": [
                source.model_dump()
                for source in _build_grounding_sources(
                    kind=kind,
                    latest_checkin=latest_checkin,
                    latest_state=latest_state,
                    recent_states=recent_states,
                    recent_git=recent_git,
                    recent_notes=recent_notes,
                    recent_workspace=recent_workspace,
                    patterns=pattern_report.get("patterns", []),
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
    recent_git: list[GitActivityRecord],
    recent_notes: list[NotesActivityRecord],
    recent_workspace: list[WorkspaceActivityRecord],
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

    if recent_git:
        commits = sum(g.commit_count for g in recent_git)
        summary = f"参考了 {len(recent_git)} 条代码活动摘要，约 {commits} 次提交，只看节奏不展示仓库路径。"
        sources.append(GroundingSource(type="git", label="近期代码活动", summary=summary))

    if recent_notes:
        new_words = sum(n.new_words for n in recent_notes)
        summary = f"参考了 {len(recent_notes)} 条笔记活动摘要，关注新增文字和主题变化。"
        if new_words:
            summary = f"参考了 {len(recent_notes)} 条笔记活动摘要，约 {new_words} 个新增词。"
        sources.append(GroundingSource(type="notes", label="近期笔记活动", summary=summary))

    if recent_workspace:
        touched = sum(w.touched_paths for w in recent_workspace)
        summary = f"参考了 {len(recent_workspace)} 条工作区活动摘要，关注项目切换和触达范围。"
        if touched:
            summary = f"参考了 {len(recent_workspace)} 条工作区活动摘要，约 {touched} 个触达路径。"
        sources.append(GroundingSource(type="workspace", label="工作区活动", summary=summary))

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
