"""actions._maybe_resume_graph — resume the checkpointer-backed graph (ADR-004 D2)."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agents.graph import graph_runner
from app.agents.graph.chat_graph import build_chat_graph
from app.core import llm as llm_module
from app.memory import event_log
from app.memory.schemas import EvidenceItem, HypothesisPayload
from app.routers import actions
from tests.conftest import StubLLM

_WRITE_CALL = {
    "content": "我帮你建一个专注块。",
    "tool_calls": [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "calendar.create_focus_block",
                "arguments": '{"title": "DW", "duration_minutes": 90, "date": "2026-06-03"}',
            },
        }
    ],
}
_FINAL = {"content": "已为你安排好专注块。", "tool_calls": []}


def _hyp(cid: str) -> HypothesisPayload:
    return HypothesisPayload(
        label="Steady", confidence=0.6, summary="x",
        evidence=[EvidenceItem(text="t", source_event_id="evt_x")],
        source_tag="chat", conversation_id=cid,
    )


async def _drive_to_interrupt(graph, cid: str) -> str:
    trigger_id = event_log.append(
        type="chat_turn",
        payload={"role": "user", "content": "x", "conversation_id": cid},
        refs={"conversation_id": cid},
    )
    async for _ in graph_runner.run_chat(
        graph=graph, llm=None, user_message="x", hypothesis=_hyp(cid),
        bundle_text="b", bundle_event_ids=[trigger_id],
        conversation_id=cid, trigger_event_id=trigger_id,
    ):
        pass
    return event_log.list_recent(types=["proposal"], limit=1)[0].id


@pytest.mark.asyncio
async def test_resume_persists_assistant_turn_when_paused(monkeypatch):
    # One shared stub instance so chat_raw advances WRITE_CALL → FINAL across
    # the act calls (a fresh stub per call would re-propose forever).
    stub = StubLLM(responses=["plan"], raw_responses=[_WRITE_CALL, _FINAL])
    monkeypatch.setattr(llm_module, "build_llm_client", lambda *a, **k: stub)
    graph = build_chat_graph(checkpointer=MemorySaver())
    cid = "conv-paused"
    pid = await _drive_to_interrupt(graph, cid)

    await actions._maybe_resume_graph(graph, cid, pid, {"ok": True})

    rows = event_log.find_refs(ref_key="conversation_id", ref_value=cid, type_="chat_turn")
    assistant = [r for r in rows if r.payload.get("role") == "assistant"]
    assert assistant, "resumed graph should persist an assistant chat_turn"
    assert assistant[0].payload.get("content") == "已为你安排好专注块。"


@pytest.mark.asyncio
async def test_resume_is_noop_when_not_paused():
    graph = build_chat_graph(checkpointer=MemorySaver())
    await actions._maybe_resume_graph(graph, "conv-none", "evt_p", {"ok": True})
    rows = event_log.find_refs(ref_key="conversation_id", ref_value="conv-none")
    assert rows == []
