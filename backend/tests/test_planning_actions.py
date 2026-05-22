from __future__ import annotations

import pytest

from app.agents.planning_agent import PlanningAgent
from app.memory.schemas import UserStateOut


def _state() -> UserStateOut:
    return UserStateOut(
        focus=7, stress=4, burnout=2, momentum=8, confidence=6, motivation=7,
        weather_label="Momentum",
    )


def test_propose_actions_focus_block_from_suggestion(fake_llm) -> None:
    agent = PlanningAgent(fake_llm)
    suggestions = [
        "今天可以安排 deep work: memory refactor",
        "建议做一段深度工作：重构记忆管道",
        "Focus: rebuild the retrieval pipeline",
    ]
    for suggestion in suggestions:
        proposals = agent.propose_actions(suggestion)
        focus_proposals = [p for p in proposals if p.kind == "focus_block"]
        assert len(focus_proposals) >= 1, f"Expected focus block for: {suggestion!r}"
        assert focus_proposals[0].requires_confirmation is True
        assert focus_proposals[0].tool_name == "calendar.create_focus_block"


def test_propose_actions_github_issue_from_checkin(fake_llm) -> None:
    agent = PlanningAgent(fake_llm)
    checkin = "I need to refactor the memory retrieval pipeline today"
    proposals = agent.propose_actions("Good work", checkin_raw=checkin)
    issue_proposals = [p for p in proposals if p.kind == "github_issue"]
    assert len(issue_proposals) >= 1
    assert issue_proposals[0].tool_name == "github.create_issue"
    assert issue_proposals[0].requires_confirmation is True


def test_propose_actions_returns_empty_for_generic_suggestion(fake_llm) -> None:
    agent = PlanningAgent(fake_llm)
    proposals = agent.propose_actions("保持节奏，不要做太多。", checkin_raw="今天状态不错")
    assert isinstance(proposals, list)


def test_propose_actions_does_not_execute(fake_llm) -> None:
    agent = PlanningAgent(fake_llm)
    proposals = agent.propose_actions("Deep Work: big refactor", checkin_raw="fix the broken auth")
    for p in proposals:
        assert p.requires_confirmation is True
