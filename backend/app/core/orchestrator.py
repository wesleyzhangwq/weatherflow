"""Orchestrator — hybrid memory write path + four agents.

Daily flow is split for clarity (Phase 1, behavior unchanged):

- **Hot path** (`Orchestrator.run_daily_interaction` / `InteractionOrchestrator`):
  ingest check-in, estimate state, reflect, then (after synchronous maintenance)
  gather hybrid memory context, detect patterns, and produce the suggestion payload.
- **Maintenance path** (`Orchestrator.run_daily_maintenance`): markdown digest,
  long-term compression, and semantic/timeline extraction.

Maintenance still runs synchronously inside the interaction method so API
semantics stay identical until a later phase moves it async/off-thread.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable, List, Optional

from app.agents import MemoryAgent, PlanningAgent, ReflectionAgent, StateAgent
from app.core.llm import LLMClient
from app.core.patterns import detect as detect_patterns
from app.memory import checkin_repo, events_repo, reflection_repo
from app.memory.context import gather_memory_context
from app.memory.schemas import CheckinRecord, ReflectionRecord, UserStateOut
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


class InteractionOrchestrator:
    """Coordinates the daily **hot** path with an explicit **maintenance** boundary.

    Phase 1: `run_daily_interaction` still `await`s maintenance synchronously so
    check-in responses and memory context stay identical to the pre-split loop.
    """

    def __init__(
        self,
        *,
        state_agent: StateAgent,
        reflection_agent: ReflectionAgent,
        planning_agent: PlanningAgent,
        memory_agent: MemoryAgent,
        llm: LLMClient,
    ) -> None:
        self.state_agent = state_agent
        self.reflection_agent = reflection_agent
        self.planning_agent = planning_agent
        self.memory_agent = memory_agent
        self._llm = llm

    @staticmethod
    def _pattern_window_days() -> int:
        return 7

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

    async def run_daily_maintenance(
        self,
        *,
        session_id: str,
        for_date: str,
        state: UserStateOut,
        reflection: ReflectionRecord,
    ) -> None:
        """Slow memory factory: digest, vectors, semantic/timeline extraction."""
        event_lines = _event_lines_for_day(session_id, for_date)
        await self.memory_agent.write_daily_markdown(
            for_date=for_date,
            state=state,
            reflection=reflection,
            event_lines=event_lines or None,
            semantic_hints=None,
        )

        await self.memory_agent.compress_to_long_term(
            for_date=for_date,
            reflection=reflection,
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

    async def run_daily_interaction(
        self,
        checkin: Optional[CheckinRecord] = None,
        *,
        session_id: str = "default",
        run_maintenance: Optional[
            Callable[..., Awaitable[None]]
        ] = None,
    ) -> DailyLoopResult:
        """Understand the moment and produce the user-facing loop result.

        Still invokes maintenance synchronously after reflection (Phase 1 —
        ordering and side effects unchanged). When ``run_maintenance`` is set
        (by ``Orchestrator``), it is used so outer subclasses can wrap the slow
        path without duplicating interaction logic.
        """
        sid = session_id or "default"
        for_date = checkin.date if checkin else _today_iso()

        if checkin is not None:
            await self.memory_agent.ingest_checkin(checkin)
            cbody = json.dumps(
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
            events_repo.add(type="checkin", content=cbody, session_id=sid)
            buffer_append(sid, {"type": "checkin", "content": cbody[:800]})

        state = await self.state_agent.estimate(checkin=checkin)
        events_repo.add(
            type="state",
            content=json.dumps(state.model_dump(), ensure_ascii=False)[:4000],
            session_id=sid,
            tags=["snapshot"],
        )
        buffer_append(
            sid,
            {
                "type": "state",
                "content": f"{state.weather_label} | {state.rationale or ''}"[:600],
            },
        )

        reflection = await self.reflection_agent.run("daily")
        events_repo.add(
            type="reflection",
            content=reflection.content,
            session_id=sid,
            tags=["daily"],
        )
        buffer_append(sid, {"type": "reflection", "content": reflection.content[:900]})

        await self.memory_agent.ingest_reflection(reflection)

        maint = run_maintenance or self.run_daily_maintenance
        await maint(
            session_id=sid,
            for_date=for_date,
            state=state,
            reflection=reflection,
        )

        mem_ctx = await gather_memory_context(
            self._llm,
            query_text=reflection.content,
            session_id=sid,
        )
        pw = self._pattern_window_days()
        pr = detect_patterns(window_days=pw).to_dict()
        pat_list: List[dict[str, Any]] = list(pr.get("patterns") or [])
        pat_summary = self._patterns_summary_for_planning(pat_list)
        suggestion = await self.planning_agent.suggest(
            state,
            recent_context=mem_ctx,
            patterns_summary=pat_summary,
        )

        return DailyLoopResult(
            state=state,
            reflection=reflection,
            suggestion=suggestion,
            patterns=pat_list,
            pattern_window_days=pw,
        )


class Orchestrator:
    def __init__(self, llm: LLMClient) -> None:
        self.state_agent = StateAgent(llm)
        self.reflection_agent = ReflectionAgent(llm)
        self.planning_agent = PlanningAgent(llm)
        self.memory_agent = MemoryAgent(llm)
        self._llm = llm
        self._interaction = InteractionOrchestrator(
            state_agent=self.state_agent,
            reflection_agent=self.reflection_agent,
            planning_agent=self.planning_agent,
            memory_agent=self.memory_agent,
            llm=self._llm,
        )

    @staticmethod
    def _pattern_window_days() -> int:
        return 7

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

    async def run_daily_interaction(
        self,
        checkin: Optional[CheckinRecord] = None,
        *,
        session_id: str = "default",
    ) -> DailyLoopResult:
        """Hot path plus planning; maintenance runs via ``run_daily_maintenance`` hook."""

        async def _maint(**kw: Any) -> None:
            await self.run_daily_maintenance(**kw)

        return await self._interaction.run_daily_interaction(
            checkin=checkin,
            session_id=session_id,
            run_maintenance=_maint,
        )

    async def run_daily_maintenance(
        self,
        *,
        session_id: str,
        for_date: str,
        state: UserStateOut,
        reflection: ReflectionRecord,
    ) -> None:
        """Expose maintenance for tests; same implementation as interaction helper."""
        await self._interaction.run_daily_maintenance(
            session_id=session_id,
            for_date=for_date,
            state=state,
            reflection=reflection,
        )

    async def daily_loop(
        self,
        checkin: Optional[CheckinRecord] = None,
        *,
        session_id: str = "default",
    ) -> DailyLoopResult:
        return await self.run_daily_interaction(checkin=checkin, session_id=session_id)

    async def weekly_loop(self, *, session_id: str = "default") -> DailyLoopResult:
        sid = session_id or "default"
        state = await self.state_agent.estimate()
        reflection = await self.reflection_agent.run("weekly")

        events_repo.add(
            type="reflection",
            content=reflection.content,
            session_id=sid,
            tags=["weekly"],
        )
        buffer_append(sid, {"type": "reflection_weekly", "content": reflection.content[:900]})

        await self.memory_agent.ingest_reflection(reflection)

        # Weekly digest bullets — light compression from reflection sentences
        raw_lines = [ln.strip() for ln in reflection.content.replace("。", ".").split(".") if ln.strip()]
        summary_bullets = raw_lines[:6] if raw_lines else [reflection.content[:240]]
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
        pw = self._pattern_window_days()
        pr = detect_patterns(window_days=pw).to_dict()
        pat_list = list(pr.get("patterns") or [])
        pat_summary = self._patterns_summary_for_planning(pat_list)
        suggestion = await self.planning_agent.suggest(
            state,
            recent_context=mem_ctx,
            patterns_summary=pat_summary,
        )

        return DailyLoopResult(
            state=state,
            reflection=reflection,
            suggestion=suggestion,
            patterns=pat_list,
            pattern_window_days=pw,
        )


__all__ = ["Orchestrator", "InteractionOrchestrator", "DailyLoopResult"]
