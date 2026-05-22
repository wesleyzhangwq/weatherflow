"""Planning Agent — at most one gentle suggestion. Never a directive."""

from __future__ import annotations

import re
from typing import Optional

from app.agents.base import BaseAgent
from app.core.model_router import model_for
from app.core.prompts import PLANNING_SYSTEM
from app.memory.schemas import ActionProposal, UserStateOut

_FALLBACK_BY_LABEL = {
    "Burnout": "这周也许可以刻意少做一点，把休息也当成正事。",
    "Overload": "试试先停掉收集新东西，把手头最小的一个闭环收个尾。",
    "Confusion": "可以试着用一句话写下「此刻最不清楚的是什么」——不用答案，命名就好。",
    "Recovery": "能回来一点点就已经很难得；保持小事、保持节奏就好。",
    "Momentum": "节奏难得，先护住它；新想法可以下周再说。",
}


class PlanningAgent(BaseAgent):
    async def suggest(
        self,
        state: UserStateOut,
        *,
        reflection_text: Optional[str] = None,
        profile: Optional[str] = None,
        dev_review_summary: Optional[str] = None,
        patterns_summary: Optional[str] = None,
    ) -> str:
        pat = (patterns_summary or "").strip() or "（本窗口暂无需要单独强调的模式信号。）"
        user = (
            f"Current weather (enum): {state.weather_label}. "
            f"focus={state.focus} stress={state.stress} burnout={state.burnout} "
            f"momentum={state.momentum} confidence={state.confidence} "
            f"motivation={state.motivation}.\n"
            f"Rationale (may be Chinese): {state.rationale or '-'}\n\n"
            f"Deterministic pattern signals (for grounding; paraphrase in Chinese, do not quote codes):\n{pat}\n\n"
            f"Latest reflection:\n{(reflection_text or '-')[:1600]}\n\n"
            f"Long-term profile markdown:\n{(profile or '-')[:2600]}\n\n"
            f"Latest developer rhythm review:\n{(dev_review_summary or '-')[:1400]}"
        )
        try:
            text = await self.llm.chat(
                [
                    {"role": "system", "content": PLANNING_SYSTEM},
                    {"role": "user", "content": user},
                ],
                model=model_for("planning"),
                temperature=0.5,
                max_tokens=220,
            )
            text = (text or "").strip()
            if not text:
                raise RuntimeError("empty suggestion")
            return text
        except Exception:
            return _FALLBACK_BY_LABEL.get(
                state.weather_label, _FALLBACK_BY_LABEL["Confusion"]
            )


    def propose_actions(
        self,
        suggestion: str,
        *,
        checkin_raw: Optional[str] = None,
    ) -> list[ActionProposal]:
        """Propose focus block or GitHub issue based on suggestion text.

        Proposals are stored without executing — callers must confirm before dispatch.
        """
        proposals: list[ActionProposal] = []

        work_pattern = re.compile(
            r"(?:deep work|focus|专注|深度工作)[：:\s]*([^\n。；]+)",
            re.IGNORECASE,
        )
        match = work_pattern.search(suggestion)
        if match:
            work_item = match.group(1).strip()[:80]
            proposals.append(
                ActionProposal(
                    kind="focus_block",
                    title=f"Deep Work: {work_item}",
                    rationale="Suggestion references a concrete focus item",
                    tool_name="calendar.create_focus_block",
                    tool_arguments={
                        "title": f"Deep Work: {work_item}",
                        "duration_minutes": 90,
                        "preferred_time": "morning",
                    },
                )
            )

        issue_pattern = re.compile(
            r"(?:issue|task|refactor|implement|fix|修复|重构|实现)[：:\s]*([^\n。；]+)",
            re.IGNORECASE,
        )
        match = issue_pattern.search(checkin_raw or "")
        if match:
            task_title = match.group(1).strip()[:100]
            proposals.append(
                ActionProposal(
                    kind="github_issue",
                    title=task_title,
                    rationale="Check-in describes a concrete engineering task",
                    tool_name="github.create_issue",
                    tool_arguments={
                        "title": task_title,
                        "body": "Created from WeatherFlow check-in.",
                        "labels": ["wf"],
                    },
                )
            )

        return proposals


__all__ = ["PlanningAgent"]
