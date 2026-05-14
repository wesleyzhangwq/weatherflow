"""Orchestrator — simple, explicit daily / weekly agent flow.

The public loop stays synchronous and easy to reason about. Internally it is
split into two phases:

1. Interaction phase: state, reflection, and one gentle suggestion.
2. Memory phase: durable writes derived from the interaction result.

This keeps the data flow readable without introducing a job queue or extra API
surface for the current product scale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, List, Optional

from app.agents import MemoryAgent, PlanningAgent, ReflectionAgent, StateAgent
from app.core.llm import LLMClient
from app.core.patterns import detect as detect_patterns
from app.memory import checkin_repo, events_repo, reflection_repo
from app.memory.context import gather_memory_context
from app.memory.reflection_context import gather_reflection_context
from app.memory.schemas import CheckinRecord, ReflectionKind, ReflectionRecord, UserStateOut
from app.memory.session_buffer import append as buffer_append


def _today_iso() -> str:
    return date.today().isoformat()


def _event_lines_for_day(session_id: str, for_date: str, limit: int = 25) -> List[str]:
    evs = events_repo.recent(limit=160, session_id=session_id)
    lines: list[str] = []
    for e in evs:
        ts = e.timestamp[:10] if e.timestamp else ""
        if ts != for_date:
            continue
        lines.append(f"{e.type}: {(e.content or '').strip()[:200]}")
        if len(lines) >= limit:
            break
    return lines


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
        self._llm = llm

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

    def _record_checkin_event(self, checkin: CheckinRecord, session_id: str) -> None:
        body = json.dumps(
            {
                "date": checkin.date,
                "status": checkin.status,
                "did_today": checkin.did_today,
                "stuck_on": checkin.stuck_on,
                "anxiety": checkin.anxiety,
                "raw": checkin.raw,
            },
            ensure_ascii=False,
        )
        events_repo.add(type="checkin", content=body, session_id=session_id)
        buffer_append(session_id, {"type": "checkin", "content": body[:800]})

    def _record_state_event(self, state: UserStateOut, session_id: str) -> None:
        events_repo.add(
            type="state",
            content=json.dumps(state.model_dump(), ensure_ascii=False)[:4000],
            session_id=session_id,
            tags=["snapshot"],
        )
        buffer_append(
            session_id,
            {
                "type": "state",
                "content": f"{state.weather_label} | {state.rationale or ''}"[:600],
            },
        )

    def _record_reflection_event(
        self,
        reflection: ReflectionRecord,
        session_id: str,
        *,
        tag: ReflectionKind,
    ) -> None:
        events_repo.add(
            type="reflection",
            content=reflection.content,
            session_id=session_id,
            tags=[tag],
        )
        buffer_append(
            session_id,
            {
                "type": "reflection" if tag == "daily" else "reflection_weekly",
                "content": reflection.content[:900],
            },
        )

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
        if checkin is not None:
            self._record_checkin_event(checkin, session_id)

        state = await self.state_agent.estimate(checkin=checkin)
        self._record_state_event(state, session_id)

        report = self._pattern_report("daily")
        patterns: List[dict[str, Any]] = list(report.get("patterns") or [])
        reflection = await self.reflection_agent.run(
            "daily",
            gather_reflection_context("daily", report),
        )
        self._record_reflection_event(reflection, session_id, tag="daily")

        mem_ctx = await gather_memory_context(
            self._llm,
            query_text=reflection.content,
            session_id=session_id,
        )
        suggestion = await self.planning_agent.suggest(
            state,
            recent_context=mem_ctx,
            patterns_summary=self._patterns_summary_for_planning(patterns),
        )

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
        if checkin is not None:
            await self.memory_agent.ingest_checkin(checkin)
        await self.memory_agent.ingest_reflection(result.reflection)

        await self.memory_agent.write_daily_markdown(
            for_date=for_date,
            state=result.state,
            reflection=result.reflection,
            event_lines=_event_lines_for_day(session_id, for_date) or None,
            semantic_hints=None,
        )

        await self.memory_agent.compress_to_long_term(
            for_date=for_date,
            reflection=result.reflection,
            extra_context="",
        )

        recent_checkins = checkin_repo.recent(limit=7)
        recent_refs = reflection_repo.recent(limit=5)
        try:
            await self.memory_agent.extract(
                recent_checkins=recent_checkins,
                recent_reflections=recent_refs,
            )
        except Exception:
            pass

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
        sid = session_id or "default"
        state = await self.state_agent.estimate()

        report = self._pattern_report("weekly")
        patterns: List[dict[str, Any]] = list(report.get("patterns") or [])
        reflection = await self.reflection_agent.run(
            "weekly",
            gather_reflection_context("weekly", report),
        )
        self._record_reflection_event(reflection, sid, tag="weekly")

        await self.memory_agent.ingest_reflection(reflection)
        summary_bullets = [
            ln.strip()
            for ln in reflection.content.replace("。", ".").split(".")
            if ln.strip()
        ][:6] or [reflection.content[:240]]
        await self.memory_agent.append_weekly_markdown(
            reflection=reflection,
            summary_bullets=summary_bullets,
        )
        await self.memory_agent.compress_to_long_term(
            for_date=_today_iso(),
            reflection=reflection,
            extra_context="weekly_review",
        )

        recent_checkins = checkin_repo.recent(limit=14)
        recent_refs = reflection_repo.recent(limit=10)
        try:
            await self.memory_agent.extract(
                recent_checkins=recent_checkins,
                recent_reflections=recent_refs,
            )
        except Exception:
            pass
        try:
            await self.memory_agent.refresh_profiles()
        except Exception:
            pass

        mem_ctx = await gather_memory_context(
            self._llm,
            query_text=reflection.content,
            session_id=sid,
        )
        suggestion = await self.planning_agent.suggest(
            state,
            recent_context=mem_ctx,
            patterns_summary=self._patterns_summary_for_planning(patterns),
        )

        return DailyLoopResult(
            state=state,
            reflection=reflection,
            suggestion=suggestion,
            patterns=patterns,
            pattern_window_days=int(report.get("window_days") or 14),
        )


__all__ = ["Orchestrator", "DailyLoopResult"]
