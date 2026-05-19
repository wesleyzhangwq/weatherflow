"""StateAgent tests with mocked LLM."""

from __future__ import annotations

import json

import pytest

from app.agents import StateAgent
from app.memory import checkin_repo, state_repo
from app.memory.schemas import CheckinIn


pytestmark = pytest.mark.asyncio


async def test_state_agent_persists_clean_json(fake_llm) -> None:
    fake_llm.queue_chat(
        json.dumps(
            {
                "focus": 72,
                "stress": 30,
                "burnout": 25,
                "momentum": 70,
                "confidence": 65,
                "motivation": 60,
                "weather_label": "Momentum",
                "rationale": "You shipped one small thing today.",
            }
        )
    )

    cid = checkin_repo.add(CheckinIn(status="alive", did_today="shipped tiny RAG"))
    record = checkin_repo.latest()
    assert record is not None and record.id == cid

    agent = StateAgent(fake_llm)
    state = await agent.estimate(checkin=record)

    assert state.weather_label == "Momentum"
    assert state.focus == 72
    assert state_repo.latest() is not None
    assert state_repo.latest().weather_label == "Momentum"


async def test_state_agent_clamps_garbage_values(fake_llm) -> None:
    fake_llm.queue_chat(
        json.dumps(
            {
                "focus": 999,
                "stress": -50,
                "burnout": "high",
                "momentum": 40,
                "confidence": 50,
                "motivation": 50,
                "weather_label": "GarbageLabel",
                "rationale": "x" * 500,
            }
        )
    )

    agent = StateAgent(fake_llm)
    state = await agent.estimate()

    assert 0 <= state.focus <= 100
    assert 0 <= state.stress <= 100
    assert state.burnout == 50  # default for unparseable
    assert state.weather_label == "Confusion"  # invalid -> safe default
    assert state.rationale and len(state.rationale) <= 240


async def test_state_agent_falls_back_to_heuristic_when_llm_fails(fake_llm) -> None:
    # No queued response -> chat will raise; agent should still return a state.
    cid = checkin_repo.add(
        CheckinIn(status="exhausted, very tired", did_today="couldn't focus")
    )
    record = checkin_repo.latest()
    assert record is not None and record.id == cid

    agent = StateAgent(fake_llm)
    state = await agent.estimate(checkin=record)

    assert state.weather_label in {"Burnout", "Confusion", "Overload", "Recovery", "Momentum"}
    rat = (state.rationale or "").lower()
    assert "burn" in rat or "heuristic" in rat or "启发" in rat or "离线" in rat


async def test_state_agent_heuristic_understands_chinese_overload(fake_llm) -> None:
    cid = checkin_repo.add(
        CheckinIn(
            status="今天信息太多，有点过载和混乱",
            did_today="切了好几个项目，但没有真正收尾",
            anxiety="担心自己又开始收集资料而不是推进",
        )
    )
    record = checkin_repo.latest()
    assert record is not None and record.id == cid

    agent = StateAgent(fake_llm)
    state = await agent.estimate(checkin=record)

    assert state.weather_label == "Overload"
    assert state.focus < 60


async def test_state_agent_heuristic_understands_chinese_momentum(fake_llm) -> None:
    cid = checkin_repo.add(
        CheckinIn(
            status="状态还可以",
            did_today="完成了一个小功能并且推进到可以发布",
        )
    )
    record = checkin_repo.latest()
    assert record is not None and record.id == cid

    agent = StateAgent(fake_llm)
    state = await agent.estimate(checkin=record)

    assert state.weather_label == "Momentum"
    assert state.momentum >= 65
