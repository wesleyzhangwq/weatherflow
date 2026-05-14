"""Orchestrator wiring: daily loop phases and stable `DailyLoopResult` shape."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.core.orchestrator import DailyLoopResult, Orchestrator
from app.memory import checkin_repo
from app.memory.schemas import CheckinIn, UserStateOut

pytestmark = pytest.mark.asyncio


def _queue_minimal_daily(fake_llm: Any) -> None:
    fake_llm.queue_chat(
        json.dumps(
            {
                "focus": 60,
                "stress": 40,
                "burnout": 30,
                "momentum": 55,
                "confidence": 50,
                "motivation": 55,
                "weather_label": "Recovery",
                "rationale": "steady",
            }
        )
    )
    fake_llm.queue_chat("今天的记录比较安静。")
    fake_llm.queue_chat(json.dumps({"patterns": []}))
    fake_llm.queue_chat(
        json.dumps({"semantic": [], "milestones": [], "phases": []}),
    )
    fake_llm.queue_chat("先保留一个小闭环。")


async def test_daily_loop_delegates_to_run_daily_interaction(fake_llm: Any) -> None:
    _queue_minimal_daily(fake_llm)
    checkin_repo.add(CheckinIn(status="ok", did_today="wrote notes"))
    record = checkin_repo.latest()
    assert record is not None

    class CountingOrchestrator(Orchestrator):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.interaction_calls = 0

        async def run_daily_interaction(
            self,
            checkin: Any = None,
            *,
            session_id: str = "default",
        ) -> DailyLoopResult:
            self.interaction_calls += 1
            return await super().run_daily_interaction(checkin=checkin, session_id=session_id)

    orch = CountingOrchestrator(fake_llm)
    await orch.daily_loop(checkin=record)
    assert orch.interaction_calls == 1


async def test_run_daily_interaction_invokes_maintenance_once(fake_llm: Any) -> None:
    _queue_minimal_daily(fake_llm)
    checkin_repo.add(CheckinIn(status="ok", did_today="wrote notes"))
    record = checkin_repo.latest()
    assert record is not None

    calls: list[int] = []

    class CountingOrchestrator(Orchestrator):
        async def run_daily_maintenance(
            self,
            *,
            session_id: str,
            for_date: str,
            state: UserStateOut,
            reflection: Any,
        ) -> None:
            calls.append(1)
            return await super().run_daily_maintenance(
                session_id=session_id,
                for_date=for_date,
                state=state,
                reflection=reflection,
            )

    await CountingOrchestrator(fake_llm).run_daily_interaction(checkin=record)
    assert calls == [1]


async def test_daily_loop_result_field_types(fake_llm: Any) -> None:
    _queue_minimal_daily(fake_llm)
    checkin_repo.add(CheckinIn(status="ok", did_today="wrote notes"))
    record = checkin_repo.latest()
    assert record is not None

    result = await Orchestrator(fake_llm).daily_loop(checkin=record)
    assert isinstance(result, DailyLoopResult)
    assert isinstance(result.state, UserStateOut)
    assert result.state.weather_label
    assert isinstance(result.reflection.content, str) and result.reflection.content
    assert isinstance(result.suggestion, str) and result.suggestion
    assert isinstance(result.patterns, list)
    assert isinstance(result.pattern_window_days, int) and result.pattern_window_days > 0
