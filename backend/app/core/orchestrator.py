"""Orchestrator — simple, explicit daily / weekly agent flow.

The public loop stays synchronous and easy to reason about. Internally it is
split into two phases:

1. Interaction phase: state, reflection, and one gentle suggestion.
2. Profile phase: refresh one readable Markdown user profile.

This keeps the data flow readable without introducing a job queue or extra API
surface for the current product scale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, List, Optional

from app.agents import MemoryAgent, PlanningAgent, ReflectionAgent, StateAgent
from app.core.llm import LLMClient
from app.core.patterns import detect as detect_patterns
from app.memory import dev_review_repo, profile_md, reflection_repo
from app.memory.reflection_context import gather_reflection_context
from app.memory.schemas import CheckinRecord, ReflectionKind, ReflectionRecord, UserStateOut


def _today_iso() -> str:
    return date.today().isoformat()


@dataclass
class DailyLoopResult:
    state: UserStateOut
    reflection: ReflectionRecord
    suggestion: str
    patterns: List[dict[str, Any]] = field(default_factory=list)
    pattern_window_days: int = 7


class Orchestrator:
    def __init__(self, llm: LLMClient) -> None:
        self.state_agent = StateAgent(llm)
        self.reflection_agent = ReflectionAgent(llm)
        self.planning_agent = PlanningAgent(llm)
        self.memory_agent = MemoryAgent(llm)

    @staticmethod
    def _pattern_window_days(kind: ReflectionKind = "daily") -> int:
        return 7 if kind == "daily" else 14

    @staticmethod
    def _patterns_summary_for_planning(pat_list: List[dict[str, Any]]) -> str:
        if not pat_list:
            return "（本窗口暂无显著模式信号。）"
        lines: list[str] = []
        for p in pat_list[:6]:
            code = p.get("code", "")
            label = p.get("label", "")
            expl = p.get("explanation", "")
            lines.append(f"- [{code}] {label}: {expl}")
        return "\n".join(lines)

    def _pattern_report(self, kind: ReflectionKind = "daily") -> dict[str, Any]:
        window = self._pattern_window_days(kind)
        try:
            return detect_patterns(window_days=window).to_dict()
        except Exception:
            return {"window_days": window, "metrics": [], "patterns": []}

    async def run_reflection_only(
        self,
        kind: ReflectionKind = "daily",
        *,
        session_id: str = "default",
    ) -> ReflectionRecord:
        """Persist a reflection only, without state/planning/memory side effects."""
        _ = session_id
        report = self._pattern_report(kind)
        return await self.reflection_agent.run(kind, gather_reflection_context(kind, report))

    async def _run_daily_interaction(
        self,
        *,
        checkin: Optional[CheckinRecord],
        session_id: str,
    ) -> DailyLoopResult:
        _ = session_id

        state = await self.state_agent.estimate(checkin=checkin)

        report = self._pattern_report("daily")
        patterns: List[dict[str, Any]] = list(report.get("patterns") or [])
        reflection = await self.reflection_agent.run(
            "daily",
            gather_reflection_context("daily", report),
        )

        suggestion = await self.planning_agent.suggest(
            state,
            reflection_text=reflection.content,
            profile=profile_md.read_profile(max_chars=3000),
            dev_review_summary=_dev_review_summary(),
            patterns_summary=self._patterns_summary_for_planning(patterns),
        )
        _attach_suggestion(reflection, suggestion)

        return DailyLoopResult(
            state=state,
            reflection=reflection,
            suggestion=suggestion,
            patterns=patterns,
            pattern_window_days=int(report.get("window_days") or 7),
        )

    async def _run_daily_memory_phase(
        self,
        *,
        checkin: Optional[CheckinRecord],
        result: DailyLoopResult,
        session_id: str,
        for_date: str,
    ) -> None:
        _ = (session_id, for_date)
        await self.memory_agent.refresh_profile(
            checkin=checkin,
            state=result.state,
            reflection=result.reflection,
            suggestion=result.suggestion,
        )

    async def daily_loop(
        self,
        checkin: Optional[CheckinRecord] = None,
        *,
        session_id: str = "default",
    ) -> DailyLoopResult:
        sid = session_id or "default"
        for_date = checkin.date if checkin else _today_iso()
        result = await self._run_daily_interaction(checkin=checkin, session_id=sid)
        await self._run_daily_memory_phase(
            checkin=checkin,
            result=result,
            session_id=sid,
            for_date=for_date,
        )
        return result

    async def weekly_loop(self, *, session_id: str = "default") -> DailyLoopResult:
        _ = session_id or "default"
        state = await self.state_agent.estimate()

        report = self._pattern_report("weekly")
        patterns: List[dict[str, Any]] = list(report.get("patterns") or [])
        reflection = await self.reflection_agent.run(
            "weekly",
            gather_reflection_context("weekly", report),
        )
        suggestion = await self.planning_agent.suggest(
            state,
            reflection_text=reflection.content,
            profile=profile_md.read_profile(max_chars=3000),
            dev_review_summary=_dev_review_summary(),
            patterns_summary=self._patterns_summary_for_planning(patterns),
        )
        _attach_suggestion(reflection, suggestion)
        await self.memory_agent.refresh_profile(
            reflection=reflection,
            state=state,
            suggestion=suggestion,
        )

        return DailyLoopResult(
            state=state,
            reflection=reflection,
            suggestion=suggestion,
            patterns=patterns,
            pattern_window_days=int(report.get("window_days") or 14),
        )


def _dev_review_summary() -> str:
    review = dev_review_repo.latest_review()
    if review is None:
        return "（暂无 Dev Review。可运行开发节奏回顾来补充 GitHub 与日历证据。）"
    lines = [
        f"Dev weather: {review.dev_weather}",
        f"Window: last {review.window_days} days",
        f"Summary: {review.summary}",
    ]
    if review.rhythm_risks:
        lines.append("Rhythm risks:")
        lines.extend(f"- {item}" for item in review.rhythm_risks[:4])
    if review.next_week_suggestion:
        lines.append(f"Suggestion: {review.next_week_suggestion}")
    return "\n".join(lines)


def _attach_suggestion(reflection: ReflectionRecord, suggestion: str) -> None:
    insights = dict(reflection.insights or {})
    insights["suggestion"] = suggestion
    reflection.insights = insights
    reflection_repo.update_insights(reflection.id, insights)


__all__ = ["Orchestrator", "DailyLoopResult"]
