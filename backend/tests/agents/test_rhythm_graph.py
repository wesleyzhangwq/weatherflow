"""Tests for the RhythmAgent subgraph (v2 M1A.6)."""

from __future__ import annotations

import pytest

from app.agents.graph.rhythm_graph import (
    after_verify,
    build_rhythm_graph,
    run_rhythm,
)


def test_build_rhythm_graph_returns_none_without_langgraph():
    """Graceful degradation when langgraph not installed."""
    graph = build_rhythm_graph()
    assert graph is None or hasattr(graph, "ainvoke")


def test_after_verify_persists_on_pass():
    state = {"critic_verdict": "pass"}
    assert after_verify(state) == "persist"


def test_after_verify_retries_on_fail():
    state = {"critic_verdict": "retry"}
    assert after_verify(state) == "hypothesize"


@pytest.mark.asyncio
async def test_run_rhythm_falls_back_to_v1(monkeypatch):
    """When langgraph not available, run_rhythm delegates to v1 orchestrator."""
    from tests.conftest import StubLLM
    from app.memory import event_log

    # Create a checkin event to serve as trigger
    eid = event_log.append(
        type="checkin",
        payload={"weather": "sunny", "project": "wf"},
    )

    # Stub LLM to return a valid hypothesis JSON referencing the checkin
    hyp_json = (
        f'{{"label": "Flow", "confidence": 0.8, "summary": "状态好", '
        f'"evidence": [{{"text": "checkin", "source_event_id": "{eid}"}}], '
        f'"counter_evidence": [], "missing_evidence": []}}'
    )
    stub = StubLLM(responses=[hyp_json])
    monkeypatch.setattr("app.core.llm.build_llm_client", lambda: stub)

    hyp_id, hyp_payload = await run_rhythm(
        trigger_event_id=eid,
        mode="checkin",
    )
    # Should succeed (via v1 fallback since langgraph not installed)
    assert hyp_id is not None
    assert hyp_id.startswith("evt_hypothesis_")
    assert hyp_payload["label"] == "Flow"
