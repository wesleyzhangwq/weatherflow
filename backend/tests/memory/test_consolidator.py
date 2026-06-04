"""L3-fast profile consolidation (ADR-006): whitelist, infer=True, critic-safety."""

from __future__ import annotations

import pytest

from app.memory import event_log
from app.memory.schemas import BundleEntry, EvidenceBundle
from app.memory.semantic import consolidator
from app.memory.semantic.consolidator import (
    _is_consolidatable,
    _render_signal,
    consolidate_event,
)


class _FakeMem:
    def __init__(self):
        self.added: list[dict] = []

    def add(self, text, *, user_id=None, infer=None, metadata=None):
        self.added.append({"text": text, "infer": infer, "metadata": metadata})


def _rec(type_, payload, refs=None):
    return event_log.get(event_log.append(type=type_, payload=payload, refs=refs or {}))


def test_whitelist_preferences_and_feedback_only():
    assert not _is_consolidatable(_rec("checkin", {"weather": "sunny"}))
    assert not _is_consolidatable(_rec("executed_action", {"tool_name": "x"}))
    assert _is_consolidatable(_rec("chat_turn", {"role": "user", "content": "我习惯早上写代码"}))
    # a non-preference chat turn is ignored
    assert not _is_consolidatable(_rec("chat_turn", {"role": "user", "content": "今天天气不错"}))
    assert _is_consolidatable(_rec("hypothesis_feedback", {"hypothesis_id": "x", "verdict": "confirmed"}))
    assert not _is_consolidatable(_rec("hypothesis_feedback", {"hypothesis_id": "x", "verdict": "unclear"}))


def test_reject_renders_counter_signal():
    h = event_log.append(type="hypothesis", payload={"label": "Overload", "summary": "多会议"})
    fb = _rec("hypothesis_feedback", {"hypothesis_id": h, "verdict": "rejected"}, refs={"target": h})
    sig = _render_signal(fb)
    assert "REJECTED" in sig and "Overload" in sig  # counter-evidence, names the pattern


@pytest.mark.asyncio
async def test_consolidate_uses_infer_true(monkeypatch):
    fake = _FakeMem()
    monkeypatch.setattr(consolidator, "_profile_memory", lambda: fake)
    pref = _rec("chat_turn", {"role": "user", "content": "我总是下午精力差"})
    assert await consolidate_event(pref) is True
    assert fake.added and fake.added[0]["infer"] is True
    assert fake.added[0]["metadata"]["last_event_id"] == pref.id


@pytest.mark.asyncio
async def test_consolidate_skips_structured_events(monkeypatch):
    fake = _FakeMem()
    monkeypatch.setattr(consolidator, "_profile_memory", lambda: fake)
    assert await consolidate_event(_rec("checkin", {"weather": "sunny"})) is False
    assert fake.added == []  # structured data never LLM-paraphrased (ADR-006 D2)


def test_live_insights_are_not_source_checked():
    """The critic only checks bundle.entries[]; live_insights must stay out of it."""
    b = EvidenceBundle(
        trigger_event_id="evt_trigger",
        mode="chat",
        entries=[BundleEntry(event_id="evt_a", event_type="checkin", rendered="x")],
        live_insights=["user is most productive on sunny mornings"],
    )
    assert b.all_event_ids() == {"evt_a"}  # live_insights NOT a citable source
    rendered = b.render()
    assert "Live Insights" in rendered
    assert "sunny mornings" in rendered
