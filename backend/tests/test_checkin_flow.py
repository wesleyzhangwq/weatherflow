"""End-to-end check-in flow with mocked LLM (orchestrator round-trip)."""

from __future__ import annotations

import json

import pytest

from app.core.orchestrator import Orchestrator
from app.memory import checkin_repo, episodic, reflection_repo, semantic, state_repo, timeline
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
    # 3) PlanningAgent (gentle suggestion; after hybrid memory context)
    fake_llm.queue_chat("今天也许只需要把一个已经开头的小闭环收个尾。")
    # 4) MemoryAgent.compress (long-term pattern extraction)
    fake_llm.queue_chat(json.dumps({"patterns": []}))
    # 5) MemoryAgent.extract JSON
    fake_llm.queue_chat(
        json.dumps(
            {
                "semantic": [
                    {
                        "key": "shipping pattern",
                        "value": "tends to ship after a quiet stretch",
                        "confidence": 0.7,
                    }
                ],
                "milestones": [
                    {
                        "title": "Returned to the project",
                        "description": "Came back after a low patch.",
                        "tags": ["recovery", "writing"],
                    }
                ],
                "phases": [],
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
    assert isinstance(saved_reflection.insights.get("grounding_sources"), list)
    assert episodic.count() >= 2  # ingested checkin + reflection
    assert any(t.title == "Returned to the project" for t in timeline.recent())
    assert any(s.key == "shipping_pattern" for s in semantic.all())
