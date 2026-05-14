"""Orchestrator — hybrid memory write path + four agents.

Daily / weekly **interaction** (hot path): check-in signals, state estimate,
single pattern pass, explicit ``ReflectionContext``, reflection + planning.

**Maintenance** (slow path): episodic ingest, markdown digest, semantic/timeline
extract, long-term compression — queued in SQLite and drained explicitly
(``drain_maintenance=True`` on ``daily_loop`` for scheduled jobs, or call
``drain_maintenance_jobs`` in tests after a check-in).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable, List, Optional

from app.agents import MemoryAgent, PlanningAgent, ReflectionAgent, StateAgent
from app.core.llm import LLMClient
from app.core.memory_maintenance import drain_maintenance_jobs
from app.core.patterns import detect as detect_patterns
from app.memory import checkin_repo, events_repo, reflection_repo
from app.memory.maintenance_repo import (
    JOB_DAILY_MEMORY,
    JOB_WEEKLY_MEMORY,
    enqueue as enqueue_maintenance_job,
)
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


class InteractionOrchestrator:
    """Coordinates the daily interaction hot path and maintenance enqueue/drain."""

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
        """Markdown → extract → compress (no episodic ingest — used by tests / direct calls)."""
        event_lines = _event_lines_for_day(session_id, for_date)
        await self.memory_agent.write_daily_markdown(
            for_date=for_date,
            state=state,
            reflection=reflection,
            event_lines=event_lines or None,
            semantic_hints=None,
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

        await self.memory_agent.compress_to_long_term(
            for_date=for_date,
            reflection=reflection,
            extra_context="",
        )

    async def run_daily_interaction(
        self,
        checkin: Optional[CheckinRecord] = None,
        *,
        session_id: str = "default",
        run_maintenance: Optional[Callable[..., Awaitable[None]]] = None,
        enqueue_maintenance: bool = True,
    ) -> DailyLoopResult:
        sid = session_id or "default"
        for_date = checkin.date if checkin else _today_iso()

        if checkin is not None:
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

        pw = 7
        try:
            pr = detect_patterns(window_days=pw).to_dict()
        except Exception:
            pr = {"window_days": pw, "metrics": [], "patterns": []}
        pat_list: List[dict[str, Any]] = list(pr.get("patterns") or [])

        rctx = gather_reflection_context("daily", pr)
        reflection = await self.reflection_agent.run("daily", rctx)
        events_repo.add(
            type="reflection",
            content=reflection.content,
            session_id=sid,
            tags=["daily"],
        )
        buffer_append(sid, {"type": "reflection", "content": reflection.content[:900]})

        if enqueue_maintenance:
            enqueue_maintenance_job(
                JOB_DAILY_MEMORY,
                {
                    "session_id": sid,
                    "for_date": for_date,
                    "checkin_id": checkin.id if checkin else None,
                    "reflection_id": reflection.id,
                    "state": state.model_dump(),
                },
            )

        if run_maintenance is not None:
            await run_maintenance(
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
            pattern_window_days=int(pr.get("window_days") or pw),
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

    async def run_reflection_only(
        self,
        kind: ReflectionKind = "daily",
        *,
        session_id: str = "default",
    ) -> ReflectionRecord:
        """Persist a reflection only (no state loop, planning, or memory maintenance)."""
        _ = session_id
        pw = 7 if kind == "daily" else 14
        try:
            pr = detect_patterns(window_days=pw).to_dict()
        except Exception:
            pr = {"window_days": pw, "metrics": [], "patterns": []}
        rctx = gather_reflection_context(kind, pr)
        return await self.reflection_agent.run(kind, rctx)

    async def run_daily_interaction(
        self,
        checkin: Optional[CheckinRecord] = None,
        *,
        session_id: str = "default",
        enqueue_maintenance: bool = True,
    ) -> DailyLoopResult:
        return await self._interaction.run_daily_interaction(
            checkin=checkin,
            session_id=session_id,
            run_maintenance=None,
            enqueue_maintenance=enqueue_maintenance,
        )

    async def run_daily_maintenance(
        self,
        *,
        session_id: str,
        for_date: str,
        state: UserStateOut,
        reflection: ReflectionRecord,
    ) -> None:
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
        drain_maintenance: bool = False,
    ) -> DailyLoopResult:
        result = await self.run_daily_interaction(checkin=checkin, session_id=session_id)
        if drain_maintenance:
            await drain_maintenance_jobs(self.memory_agent)
        return result

    async def weekly_loop(
        self,
        *,
        session_id: str = "default",
        drain_maintenance: bool = False,
    ) -> DailyLoopResult:
        sid = session_id or "default"
        state = await self.state_agent.estimate()

        pw = 14
        try:
            pr = detect_patterns(window_days=pw).to_dict()
        except Exception:
            pr = {"window_days": pw, "metrics": [], "patterns": []}
        pat_list = list(pr.get("patterns") or [])

        rctx = gather_reflection_context("weekly", pr)
        reflection = await self.reflection_agent.run("weekly", rctx)

        events_repo.add(
            type="reflection",
            content=reflection.content,
            session_id=sid,
            tags=["weekly"],
        )
        buffer_append(sid, {"type": "reflection_weekly", "content": reflection.content[:900]})

        raw_lines = [ln.strip() for ln in reflection.content.replace("。", ".").split(".") if ln.strip()]
        summary_bullets = raw_lines[:6] if raw_lines else [reflection.content[:240]]

        enqueue_maintenance_job(
            JOB_WEEKLY_MEMORY,
            {
                "session_id": sid,
                "reflection_id": reflection.id,
                "summary_bullets": summary_bullets,
            },
        )

        mem_ctx = await gather_memory_context(
            self._llm,
            query_text=reflection.content,
            session_id=sid,
        )
        pat_summary = self._patterns_summary_for_planning(pat_list)
        suggestion = await self.planning_agent.suggest(
            state,
            recent_context=mem_ctx,
            patterns_summary=pat_summary,
        )

        result = DailyLoopResult(
            state=state,
            reflection=reflection,
            suggestion=suggestion,
            patterns=pat_list,
            pattern_window_days=int(pr.get("window_days") or pw),
        )
        if drain_maintenance:
            await drain_maintenance_jobs(self.memory_agent)
        return result


__all__ = ["Orchestrator", "InteractionOrchestrator", "DailyLoopResult"]
