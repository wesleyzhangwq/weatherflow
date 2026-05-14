"""Reflection grounding metadata tests."""

from __future__ import annotations

import pytest

from app.agents import ReflectionAgent
from app.memory import checkin_repo, state_repo
from app.memory.schemas import CheckinIn, UserStateOut

pytestmark = pytest.mark.asyncio


async def test_weekly_reflection_includes_grounding_sources(fake_llm) -> None:
    checkin_repo.add(CheckinIn(status="slow but steady", did_today="closed one loop"))
    state_repo.add(
        UserStateOut(
            focus=62,
            stress=38,
            burnout=32,
            momentum=58,
            confidence=55,
            motivation=57,
            weather_label="Recovery",
            rationale="You are moving again without forcing it.",
        )
    )
    fake_llm.queue_chat("这一周的线索很安静，但它们没有消失。")

    reflection = await ReflectionAgent(fake_llm).run("weekly")

    assert reflection.insights is not None
    sources = reflection.insights.get("grounding_sources")
    assert isinstance(sources, list)
    source_types = {source["type"] for source in sources}
    assert {"checkin", "state", "patterns"}.issubset(source_types)
    assert all(source["label"] and source["summary"] for source in sources)


async def test_daily_reflection_fallback_is_simplified_chinese(fake_llm) -> None:
    checkin_repo.add(CheckinIn(status="有点累", did_today="写了几句"))
    state_repo.add(
        UserStateOut(
            focus=55,
            stress=50,
            burnout=45,
            momentum=48,
            confidence=50,
            motivation=50,
            weather_label="Confusion",
            rationale="今天节奏不算快，但你还在场。",
        )
    )
    # No queue_chat -> chat raises -> fallback path
    reflection = await ReflectionAgent(fake_llm).run("daily")
    assert "你" in reflection.content
    assert "Today was today" not in reflection.content
    assert reflection.kind == "daily"
