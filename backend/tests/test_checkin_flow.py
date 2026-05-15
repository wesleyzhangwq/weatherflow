"""End-to-end check-in flow with mocked LLM (orchestrator round-trip)."""

from __future__ import annotations

import json

import pytest

from app.core.orchestrator import Orchestrator
from app.memory import checkin_repo, profile_md, reflection_repo, state_repo
from app.memory.schemas import CheckinIn

pytestmark = pytest.mark.asyncio


async def test_full_daily_loop_writes_everything(fake_llm) -> None:
    # Programmed responses, in the order the orchestrator will request them:
    # 1) StateAgent JSON
    fake_llm.queue_chat(
        json.dumps(
            {
                "focus": 60,
                "stress": 45,
                "burnout": 35,
                "momentum": 55,
                "confidence": 50,
                "motivation": 55,
                "weather_label": "Recovery",
                "rationale": "You came back today after a quiet stretch.",
            }
        )
    )
    # 2) ReflectionAgent (daily) prose
    fake_llm.queue_chat(
        "你来了，也把卡住的东西说了出来。这是一种很安静、也很真实的进展。"
    )
    # 3) PlanningAgent (gentle suggestion)
    fake_llm.queue_chat("今天也许只需要把一个已经开头的小闭环收个尾。")
    # 4) MemoryAgent.refresh_profile JSON
    fake_llm.queue_chat(
        json.dumps(
            {
                "user_profile": "你会在安静一阵之后重新回到项目。",
                "behavior_patterns": "- 小闭环能帮助你恢复节奏。",
                "goals": "- 避免同时打开太多教程。",
            }
        )
    )

    payload = CheckinIn(
        status="okay-ish",
        did_today="wrote a small note",
        stuck_on="naming what I want next",
        anxiety="too many tutorials open",
    )
    checkin_repo.add(payload)
    record = checkin_repo.latest()
    assert record is not None

    orch = Orchestrator(fake_llm)
    result = await orch.daily_loop(checkin=record)

    assert result.state.weather_label == "Recovery"
    assert "小闭环" in result.suggestion or len(result.suggestion) > 3
    assert isinstance(result.patterns, list)
    assert "进展" in result.reflection.content
    assert result.reflection.insights is not None
    sources = result.reflection.insights.get("grounding_sources")
    assert isinstance(sources, list)
    source_types = {source["type"] for source in sources}
    assert {"checkin", "state", "patterns"}.issubset(source_types)
    for source in sources:
        assert set(source) == {"type", "label", "summary"}
        assert source["label"]
        assert source["summary"]
        assert len(source["summary"]) <= 140
    summaries = " ".join(source["summary"] for source in sources)
    assert "too many tutorials open" not in summaries
    assert "Write the reflection" not in summaries

    # Persistence checks
    assert state_repo.latest() is not None
    saved_reflection = reflection_repo.recent(limit=1)[0]
    assert saved_reflection.kind == "daily"
    assert saved_reflection.insights is not None
    assert saved_reflection.insights.get("suggestion") == result.suggestion
    assert isinstance(saved_reflection.insights.get("grounding_sources"), list)
    assert "小闭环" in profile_md.read_profile()
