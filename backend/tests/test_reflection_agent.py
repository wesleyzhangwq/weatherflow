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
