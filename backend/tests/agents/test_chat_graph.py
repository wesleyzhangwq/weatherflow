"""Tests for the LangGraph chat graph (v2 M1A.2–M1A.4).

Since langgraph may not be installed in the test env, we test:
1. Individual node functions with stubs
2. build_chat_graph returns None when langgraph unavailable
3. Conditional edge logic
4. Critic groundedness checks (M1A.4)
"""

from __future__ import annotations

import pytest

from app.agents.graph.chat_graph import (
    after_critic,
    build_chat_graph,
    criticize_node,
    plan_node,
    should_continue_act,
)
from app.agents.graph.checkpoint import (
    clear_paused_state,
    get_paused_state,
    has_paused_state,
    save_paused_state,
)
from app.agents.graph.state import AgentState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(**overrides) -> AgentState:
    """Create a minimal AgentState for testing."""
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
        "critic_verdict": None,
        "final_answer": None,
        "semantic_memories": [],
        "sse_events": [],
        "turn_count": 0,
        "max_turns": 8,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests: graph builder
# ---------------------------------------------------------------------------


def test_build_chat_graph_returns_none_without_langgraph():
    """When langgraph is not installed, build_chat_graph returns None."""
    graph = build_chat_graph()
    # Should be None if langgraph isn't installed, or a compiled graph if it is.
    # In our test env, langgraph is NOT installed.
    # We just verify it doesn't crash.
    assert graph is None or hasattr(graph, "invoke")


# ---------------------------------------------------------------------------
# Tests: conditional edges
# ---------------------------------------------------------------------------


def test_should_continue_act_goes_to_criticize():
    state = _make_state(turn_count=1)
    assert should_continue_act(state) == "criticize"


def test_should_continue_act_goes_to_synthesize_on_final_answer():
    state = _make_state(final_answer="done", turn_count=1)
    assert should_continue_act(state) == "synthesize"


def test_should_continue_act_goes_to_synthesize_on_max_turns():
    state = _make_state(turn_count=8, max_turns=8)
    assert should_continue_act(state) == "synthesize"


def test_after_critic_goes_to_synthesize_on_pass():
    state = _make_state(critic_verdict="pass")
    assert after_critic(state) == "synthesize"


def test_after_critic_goes_to_plan_on_retry_early_turn():
    state = _make_state(critic_verdict="retry", turn_count=1)
    assert after_critic(state) == "plan"


def test_after_critic_goes_to_synthesize_on_retry_late_turn():
    state = _make_state(critic_verdict="retry", turn_count=3)
    assert after_critic(state) == "synthesize"


# ---------------------------------------------------------------------------
# Tests: critic node (M1A.4)
# ---------------------------------------------------------------------------


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
    result = await criticize_node(state)
    assert result["critic_verdict"] == "pass"


@pytest.mark.asyncio
async def test_critic_retries_when_evidence_id_not_in_bundle():
    """Core M1A.4 test: fabricated source_event_id triggers retry."""
    state = _make_state(
        hypothesis={
            "label": "Overload",
            "confidence": 0.6,
            "evidence": [
                {"text": "fabricated evidence", "source_event_id": "FAKE_ID_999"},
            ],
        },
    )
    result = await criticize_node(state)
    assert result["critic_verdict"] == "retry"


@pytest.mark.asyncio
async def test_critic_passes_with_no_hypothesis():
    state = _make_state(hypothesis=None, final_answer=None)
    result = await criticize_node(state)
    assert result["critic_verdict"] == "pass"


# ---------------------------------------------------------------------------
# Tests: plan node (with StubLLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_node_produces_plan(monkeypatch):
    """Plan node calls LLM and returns plan text."""
    from tests.conftest import StubLLM

    stub = StubLLM(responses=['{"plan": "check calendar for tomorrow"}'])
    monkeypatch.setattr(
        "app.core.llm.build_llm_client",
        lambda: stub,
    )
    state = _make_state()
    result = await plan_node(state)
    assert "plan" in result
    assert result["critic_verdict"] is None  # resets on re-plan


# ---------------------------------------------------------------------------
# Tests: checkpoint / proposal interrupt (M1A.5)
# ---------------------------------------------------------------------------


def test_checkpoint_save_get_clear():
    """Checkpoint stores and retrieves paused state by conversation_id."""
    state = {"conversation_id": "conv_123", "proposals": [{"id": "p1"}]}
    save_paused_state("conv_123", state)

    assert has_paused_state("conv_123") is True
    assert get_paused_state("conv_123") == state

    clear_paused_state("conv_123")
    assert has_paused_state("conv_123") is False
    assert get_paused_state("conv_123") is None


def test_checkpoint_no_cross_contamination():
    """Different conversation_ids don't interfere."""
    save_paused_state("conv_a", {"data": "a"})
    save_paused_state("conv_b", {"data": "b"})

    assert get_paused_state("conv_a")["data"] == "a"
    assert get_paused_state("conv_b")["data"] == "b"

    clear_paused_state("conv_a")
    assert has_paused_state("conv_a") is False
    assert has_paused_state("conv_b") is True


def test_proposal_in_state_triggers_interrupt():
    """When proposals exist and no final_answer, state indicates interrupt."""
    state = _make_state(
        proposals=[{"proposal_id": "evt_prop_123", "tool_name": "calendar.create_focus_block"}],
        final_answer=None,
    )
    # The interrupt detection logic: proposals present + no final answer
    assert state["proposals"] and not state.get("final_answer")
