"""GraphRunner — real HITL interrupt → resume cycle (ADR-004 D2).

langgraph is installed, so we drive the compiled chat graph (with an in-memory
checkpointer) through a write Proposal: it pauses at human_review, then resumes
to a final answer. A registered write tool (calendar.create_focus_block) makes
dispatch produce a Proposal without any MCP call.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agents.graph import graph_runner
from app.agents.graph.chat_graph import build_chat_graph
from app.core import llm as llm_module
from app.memory import event_log
from app.memory.schemas import EvidenceItem, HypothesisPayload
from tests.conftest import StubLLM

_WRITE_CALL = {
    "content": "我帮你建一个专注块。",
    "tool_calls": [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "calendar.create_focus_block",
                "arguments": '{"title": "Deep work", "duration_minutes": 90, "date": "2026-06-03"}',
            },
        }
    ],
}
_FINAL = {"content": "已为你安排好专注块。", "tool_calls": []}


def _stub() -> StubLLM:
    # chat: plan node; chat_raw: act node (write call, then final answer on resume)
    return StubLLM(responses=["计划：创建专注块。"], raw_responses=[_WRITE_CALL, _FINAL])


def _hyp(cid: str) -> HypothesisPayload:
    return HypothesisPayload(
        label="Steady",
        confidence=0.6,
        summary="平稳推进。",
        evidence=[EvidenceItem(text="trigger", source_event_id="evt_x")],
        source_tag="chat",
        conversation_id=cid,
    )


@pytest.mark.asyncio
async def test_write_proposal_pauses_then_resumes(monkeypatch):
    stub = _stub()
    monkeypatch.setattr(llm_module, "build_llm_client", lambda *a, **k: stub)
    graph = build_chat_graph(checkpointer=MemorySaver())
    cid = "conv-hitl"
    # load_context needs a real trigger event in L1.
    trigger_id = event_log.append(
        type="chat_turn",
        payload={"role": "user", "content": "帮我建个专注块", "conversation_id": cid},
        refs={"conversation_id": cid},
    )

    # 1) Run → graph pauses at the write proposal (interrupt).
    events = [
        ev
        async for ev in graph_runner.run_chat(
            graph=graph,
            llm=stub,
            user_message="帮我建个专注块",
            hypothesis=_hyp(cid),
            bundle_text="bundle",
            bundle_event_ids=[trigger_id],
            conversation_id=cid,
            trigger_event_id=trigger_id,
        )
    ]
    names = [e["event"] for e in events]
    assert "proposal_created" in names
    assert "final_answer" not in names  # paused before answering
    assert await graph_runner.has_pending_interrupt(graph, cid) is True

    proposals = event_log.list_recent(types=["proposal"], limit=5)
    assert proposals, "the write tool should have created a Proposal in L1"
    proposal_id = proposals[0].id

    # 2) Resume → graph continues to a final answer, no longer paused.
    resumed = [
        ev
        async for ev in graph_runner.resume_chat(
            graph=graph,
            conversation_id=cid,
            proposal_id=proposal_id,
            execution_result={"ok": True},
        )
    ]
    assert any(e["event"] == "final_answer" for e in resumed)
    assert await graph_runner.has_pending_interrupt(graph, cid) is False


@pytest.mark.asyncio
async def test_has_pending_interrupt_false_for_unknown_conversation():
    graph = build_chat_graph(checkpointer=MemorySaver())
    assert await graph_runner.has_pending_interrupt(graph, "never-seen") is False
