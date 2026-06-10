"""Multi-turn chat contract: history window + assistant persistence + deltas.

Three behaviours that died silently in earlier rounds, pinned here:
1. the assistant's final answer lands in L1 as a chat_turn (so /history can
   rehydrate it and the next turn can see it);
2. a follow-up turn's LLM messages include the previous user AND assistant
   turns (the graph state alone cannot provide this — it is rebuilt per turn);
3. when the LLM client supports chat_raw_stream, answer_delta SSE events
   precede final_answer.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.core import llm as llm_module
from app.main import create_app
from app.memory import event_log

HYP_JSON = (
    '{{"label": "Steady", "confidence": 0.6, "summary": "平稳推进。", '
    '"evidence": [{{"text": "本轮消息", "source_event_id": "{eid}"}}], '
    '"counter_evidence": [], "missing_evidence": []}}'
)

ANSWER_1 = "记住了：42。"
ANSWER_2 = "你刚才说的数字是 42。"


class _RecordingLLM:
    """Scripted client that records every chat_raw(_stream) message list."""

    def __init__(self):
        self.raw_calls: list[list[dict]] = []
        self._answers = [ANSWER_1, ANSWER_2]

    async def chat(self, messages, **kw):
        # Serves both the first-turn hypothesis JSON and the plan node.
        turns = event_log.latest_by_type(["chat_turn"], limit=1)
        eid = turns[0].id if turns else "evt_chat_unknown"
        return HYP_JSON.format(eid=eid)

    async def chat_raw(self, messages, **kw):
        self.raw_calls.append(list(messages))
        answer = self._answers.pop(0) if self._answers else ANSWER_2
        return {"content": answer, "tool_calls": []}

    async def chat_raw_stream(self, messages, *, on_delta, **kw):
        msg = await self.chat_raw(messages, **kw)
        on_delta(msg["content"])
        return msg

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_chat_multiturn_context_persistence_and_deltas(monkeypatch):
    stub = _RecordingLLM()
    monkeypatch.setattr(llm_module, "build_llm_client", lambda *a, **k: stub)
    monkeypatch.setattr(main_module, "build_llm_client", lambda *a, **k: stub)

    app = create_app()
    cid = "conv-multiturn-1"
    with TestClient(app) as client:
        # ---- turn 1
        r1 = client.post(
            "/api/chat/stream",
            json={"message": "请记住这个数字：42", "conversation_id": cid},
        )
        assert r1.status_code == 200, r1.text
        events1 = re.findall(r"^event:\s*(\S+)", r1.text, re.MULTILINE)
        assert "answer_delta" in events1, events1
        assert events1[-1] == "final_answer"
        assert events1.index("answer_delta") < events1.index("final_answer")

        # assistant reply persisted to L1
        rows = event_log.find_refs(
            ref_key="conversation_id", ref_value=cid, type_="chat_turn", limit=10
        )
        roles = sorted(r.payload.get("role") for r in rows)
        assert roles == ["assistant", "user"], roles
        assistant_row = next(r for r in rows if r.payload["role"] == "assistant")
        assert assistant_row.payload["content"] == ANSWER_1

        # ---- turn 2: follow-up must see turn 1 (both sides) in its messages
        r2 = client.post(
            "/api/chat/stream",
            json={"message": "我刚才让你记的数字是多少？", "conversation_id": cid},
        )
        assert r2.status_code == 200, r2.text

        second_call_msgs = stub.raw_calls[-1]
        contents = [str(m.get("content") or "") for m in second_call_msgs]
        assert any("请记住这个数字：42" in c for c in contents), contents
        assert any(ANSWER_1 in c for c in contents), contents

        # ---- /history rehydrates both assistant replies
        hist = client.get(f"/api/chat/{cid}/history").json()
        kinds = [h["kind"] for h in hist]
        assert kinds.count("user_message") == 2
        assert kinds.count("final_answer") == 2
