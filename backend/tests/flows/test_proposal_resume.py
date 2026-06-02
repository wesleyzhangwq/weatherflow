"""actions._maybe_resume_graph — resume a paused graph after proposal exec (G3/M1A.5)."""

from __future__ import annotations

import pytest

from app.agents.graph.checkpoint import clear_paused_state, save_paused_state
from app.core import llm as llm_module
from app.memory import event_log
from app.routers.actions import _maybe_resume_graph
from tests.conftest import StubLLM


@pytest.mark.asyncio
async def test_resume_persists_assistant_turn_when_graph_paused(monkeypatch):
    # resume_chat synthesizes a closing answer via the LLM — stub it.
    monkeypatch.setattr(
        llm_module, "build_llm_client", lambda *a, **k: StubLLM(["已为你创建好了。"])
    )

    cid = "conv-paused"
    save_paused_state(cid, {"messages": [{"role": "user", "content": "帮我建个专注块"}]})
    try:
        await _maybe_resume_graph(cid, "evt_proposal_42", {"ok": True})
    finally:
        clear_paused_state(cid)

    rows = event_log.find_refs(
        ref_key="conversation_id", ref_value=cid, type_="chat_turn"
    )
    assistant_turns = [r for r in rows if r.payload.get("role") == "assistant"]
    assert assistant_turns, "resumed graph should persist an assistant chat_turn"
    assert assistant_turns[0].payload.get("content") == "已为你创建好了。"


@pytest.mark.asyncio
async def test_resume_is_noop_without_paused_state(monkeypatch):
    monkeypatch.setattr(
        llm_module, "build_llm_client", lambda *a, **k: StubLLM([])
    )
    cid = "conv-not-paused"
    await _maybe_resume_graph(cid, "evt_proposal_99", {"ok": True})
    rows = event_log.find_refs(ref_key="conversation_id", ref_value=cid)
    assert rows == []
