"""Tests for the LangGraph chat graph (M1A.2–M1A.4 + ADR-004 D2 routing).

langgraph is installed, so the graph compiles for real. We test node functions,
conditional-edge routing (incl. the HITL human_review branch), and the critic
groundedness check.
"""

from __future__ import annotations

import pytest

from app.agents.graph.chat_graph import (
    after_critic,
    build_chat_graph,
    criticize_node,
    plan_node,
    route_after_act,
)
from app.agents.graph.state import AgentState


def _make_state(**overrides) -> AgentState:
    base: AgentState = {
        "messages": [],
        "conversation_id": "conv_test",
        "user_id": "default",
        "bundle_text": "=== Evidence Bundle ===\n[event-001] checkin\n",
        "bundle_event_ids": ["event-001", "event-002"],
        "trigger_event_id": "event-001",
        "hypothesis": None,
        "hypothesis_id": None,
        "plan": None,
        "observations": [],
        "proposals": [],
        "pending_proposal": None,
        "critic_verdict": None,
        "final_answer": None,
        "semantic_memories": [],
        "sse_events": [],
        "turn_count": 0,
        "max_turns": 8,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------- builder


def test_build_chat_graph_compiles_with_hitl_nodes():
    graph = build_chat_graph()
    assert graph is not None and hasattr(graph, "ainvoke")
    nodes = set(graph.get_graph().nodes.keys())
    assert {"act", "human_review", "criticize", "synthesize"} <= nodes


# ----------------------------------------------------------- conditional edges


def test_route_after_act_default_to_criticize():
    assert route_after_act(_make_state(turn_count=1)) == "criticize"


def test_route_after_act_synthesize_on_final_answer():
    assert route_after_act(_make_state(final_answer="done", turn_count=1)) == "synthesize"


def test_route_after_act_synthesize_on_max_turns():
    assert route_after_act(_make_state(turn_count=8, max_turns=8)) == "synthesize"


def test_route_after_act_human_review_on_pending_proposal():
    """ADR-004 D2: a pending write proposal routes to the HITL pause node."""
    state = _make_state(
        pending_proposal={"proposal_id": "evt_prop_1", "tool_call_id": "call_1"},
        turn_count=1,
    )
    assert route_after_act(state) == "human_review"


def test_after_critic_goes_to_synthesize_on_pass():
    assert after_critic(_make_state(critic_verdict="pass")) == "synthesize"


def test_after_critic_goes_to_plan_on_retry_early_turn():
    assert after_critic(_make_state(critic_verdict="retry", turn_count=1)) == "plan"


def test_after_critic_goes_to_synthesize_on_retry_late_turn():
    assert after_critic(_make_state(critic_verdict="retry", turn_count=3)) == "synthesize"


# ----------------------------------------------------------- critic node (M1A.4)


@pytest.mark.asyncio
async def test_critic_passes_when_all_evidence_ids_in_bundle():
    state = _make_state(
        hypothesis={
            "label": "Steady",
            "confidence": 0.7,
            "evidence": [
                {"text": "checkin data", "source_event_id": "event-001"},
                {"text": "github data", "source_event_id": "event-002"},
            ],
        },
    )
    assert (await criticize_node(state))["critic_verdict"] == "pass"


@pytest.mark.asyncio
async def test_critic_retries_when_evidence_id_not_in_bundle():
    """Core M1A.4 test: fabricated source_event_id triggers retry."""
    state = _make_state(
        hypothesis={
            "label": "Overload",
            "confidence": 0.6,
            "evidence": [{"text": "fabricated", "source_event_id": "FAKE_ID_999"}],
        },
    )
    assert (await criticize_node(state))["critic_verdict"] == "retry"


@pytest.mark.asyncio
async def test_critic_passes_with_no_hypothesis():
    assert (await criticize_node(_make_state(hypothesis=None, final_answer=None)))[
        "critic_verdict"
    ] == "pass"


# ----------------------------------------------------------- plan node (StubLLM)


@pytest.mark.asyncio
async def test_plan_node_produces_plan(monkeypatch):
    from tests.conftest import StubLLM

    stub = StubLLM(responses=['{"plan": "check calendar for tomorrow"}'])
    monkeypatch.setattr("app.core.llm.build_llm_client", lambda: stub)
    result = await plan_node(_make_state())
    assert "plan" in result
    assert result["critic_verdict"] is None
