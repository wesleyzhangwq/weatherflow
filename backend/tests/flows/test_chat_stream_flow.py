"""T4 chat SSE stream — event ordering contract (§10.2) end-to-end (G13).

/api/chat/stream runs the LangGraph chat graph via run_chat. We stub the
hypothesis LLM call and the function-calling HTTP call so no network is touched,
and assert the SSE event order.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.core import llm as llm_module
from app.main import create_app

HYP_JSON = (
    '{{"label": "Steady", "confidence": 0.6, "summary": "平稳推进。", '
    '"evidence": [{{"text": "本轮消息", "source_event_id": "{eid}"}}], '
    '"counter_evidence": [], "missing_evidence": []}}'
)


class _ScriptedLLM:
    """Drives the real chat graph: chat() returns the hypothesis JSON (also used
    as the plan), chat_raw() returns a content-only final answer (no tool call)
    so act terminates cleanly."""

    def __init__(self):
        from app.memory import event_log

        self._event_log = event_log

    async def chat(self, messages, **kw):
        turns = self._event_log.latest_by_type(["chat_turn"], limit=1)
        eid = turns[0].id if turns else "evt_chat_unknown"
        return HYP_JSON.format(eid=eid)

    async def chat_raw(self, messages, **kw):
        return {"content": "你今天节奏平稳，继续保持。", "tool_calls": []}

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_chat_stream_event_order(monkeypatch):
    stub = _ScriptedLLM()
    monkeypatch.setattr(llm_module, "build_llm_client", lambda *a, **k: stub)
    monkeypatch.setattr(main_module, "build_llm_client", lambda *a, **k: stub)

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/chat/stream",
            json={"message": "我今天状态如何？", "conversation_id": "conv-stream-1"},
        )
        assert resp.status_code == 200, resp.text
        # Robust to both \n and \r\n SSE line endings (no trailing anchor).
        events = re.findall(r"^event:\s*(\S+)", resp.text, re.MULTILINE)

    # §10.2 ordering: context first, hypothesis on the first turn, answer last.
    assert events, f"no SSE events parsed from: {resp.text!r}"
    assert events[0] == "context_loaded"
    assert "hypothesis_generated" in events
    assert events[-1] == "final_answer"
    assert (
        events.index("context_loaded")
        < events.index("hypothesis_generated")
        < events.index("final_answer")
    )
