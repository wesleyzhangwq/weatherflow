"""Tests for graph_runner — v1 fallback + proposal interrupt/resume (G10/M1A.5).

langgraph is not installed in this environment, so build_chat_graph() returns
None and run_chat/resume_chat exercise their v1 fallback paths.
"""

from __future__ import annotations

import pytest

from app.agents import chat_agent
from app.agents.graph import graph_runner
from app.agents.graph.checkpoint import (
    clear_paused_state,
    has_paused_state,
    save_paused_state,
)
from app.memory.schemas import EvidenceItem, HypothesisPayload


def _hyp() -> HypothesisPayload:
    return HypothesisPayload(
        label="Steady",
        confidence=0.6,
        summary="平稳推进。",
        evidence=[EvidenceItem(text="trigger", source_event_id="evt_x")],
        source_tag="chat",
        conversation_id="conv-1",
    )


@pytest.mark.asyncio
async def test_run_chat_falls_back_to_v1_chatagent(monkeypatch):
    """When the chat graph is unavailable, run_chat routes through the v1
    ChatAgent and still emits a final_answer SSE event.

    We force the graph off (build_chat_graph -> None) so this is deterministic
    regardless of whether langgraph is installed in the environment."""
    monkeypatch.setattr(graph_runner, "build_chat_graph", lambda *a, **k: None)

    async def fake_chat_call(self, messages, *, tools):
        return {"content": "这是最终回答。", "tool_calls": []}

    monkeypatch.setattr(chat_agent.ChatAgent, "_chat_call", fake_chat_call)

    from tests.conftest import StubLLM

    events = []
    async for ev in graph_runner.run_chat(
        llm=StubLLM([]),
        user_message="hi",
        hypothesis=_hyp(),
        bundle_text="bundle",
        bundle_event_ids=["evt_x"],
        conversation_id="conv-1",
        trigger_event_id="evt_x",
    ):
        events.append(ev["event"])

    assert "final_answer" in events


@pytest.mark.asyncio
async def test_resume_chat_synthesizes_final_answer_and_clears_state():
    from tests.conftest import StubLLM

    cid = "conv-resume"
    save_paused_state(cid, {"messages": [{"role": "user", "content": "帮我建专注块"}]})
    try:
        events = [
            ev
            async for ev in graph_runner.resume_chat(
                llm=StubLLM(["已为你创建专注块，注意休息。"]),
                conversation_id=cid,
                proposal_id="evt_proposal_1",
                execution_result={"ok": True},
            )
        ]
    finally:
        clear_paused_state(cid)

    finals = [e for e in events if e["event"] == "final_answer"]
    assert finals, "resume should emit a final_answer"
    assert "专注块" in finals[0]["data"]
    # resume_chat must clear the paused state once consumed
    assert not has_paused_state(cid)


@pytest.mark.asyncio
async def test_resume_chat_without_paused_state_yields_nothing():
    from tests.conftest import StubLLM

    events = [
        ev
        async for ev in graph_runner.resume_chat(
            llm=StubLLM([]),
            conversation_id="conv-never-paused",
            proposal_id="p",
            execution_result=None,
        )
    ]
    assert events == []
