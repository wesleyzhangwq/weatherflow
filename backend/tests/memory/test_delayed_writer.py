"""DelayedMemoryWriter — the 4-gate logic from §9.2."""

from __future__ import annotations

import json

import pytest

from app.memory import delayed_writer, event_log


def _confirmed_hyp(label: str = "Overload", ts: str | None = None) -> str:
    cid = event_log.append(type="checkin", payload={"weather": "rainy"})
    hyp_id = event_log.append(
        type="hypothesis",
        payload={
            "label": label,
            "confidence": 0.7,
            "summary": "s",
            "evidence": [{"text": "x", "source_event_id": cid}],
            "counter_evidence": [],
            "missing_evidence": [],
            "source_tag": "checkin",
        },
        refs={"triggered_by": cid},
        timestamp=ts,
    )
    event_log.append(
        type="hypothesis_feedback",
        payload={"hypothesis_id": hyp_id, "verdict": "confirmed"},
        refs={"target": hyp_id},
    )
    return hyp_id


class _StubLLM:
    def __init__(self, diff_text: str, confidence: float):
        self._diff = diff_text
        self._conf = confidence
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        return json.dumps({"diff": self._diff, "confidence": self._conf})

    async def embed(self, texts, **kw):
        return [[0.0] for _ in texts]

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_low_confidence_blocks_patch():
    for _ in range(3):
        _confirmed_hyp("Overload")  # meets repetition threshold
    llm = _StubLLM(diff_text="- 新条目", confidence=0.4)  # below 0.6 → blocked
    result = await delayed_writer.maybe_update(llm=llm)
    assert all(p.get("section") != "Anti-patterns" for p in result.get("patches_applied", []))


@pytest.mark.asyncio
async def test_repetition_threshold_blocks_single_confirmation():
    _confirmed_hyp("Overload")
    llm = _StubLLM(diff_text="- 新条目", confidence=0.9)
    result = await delayed_writer.maybe_update(llm=llm)
    # Only 1 confirmation < 3 → no Anti-patterns patch
    assert all(p["section"] != "Anti-patterns" for p in result.get("patches_applied", []))


@pytest.mark.asyncio
async def test_full_gate_pass_applies_patch():
    for _ in range(3):
        _confirmed_hyp("Overload")
    llm = _StubLLM(diff_text="- Overload 信号: 会议 >=4 + DL 任务并行", confidence=0.85)
    result = await delayed_writer.maybe_update(llm=llm)
    sections = [p["section"] for p in result["patches_applied"]]
    assert "Anti-patterns" in sections


@pytest.mark.asyncio
async def test_rejected_hypothesis_does_not_pass_whitelist():
    cid = event_log.append(type="checkin", payload={"weather": "rainy"})
    h = event_log.append(
        type="hypothesis",
        payload={
            "label": "Overload",
            "confidence": 0.7,
            "summary": "s",
            "evidence": [{"text": "x", "source_event_id": cid}],
            "counter_evidence": [],
            "missing_evidence": [],
            "source_tag": "checkin",
        },
        refs={"triggered_by": cid},
    )
    event_log.append(
        type="hypothesis_feedback",
        payload={"hypothesis_id": h, "verdict": "rejected"},
        refs={"target": h},
    )
    llm = _StubLLM(diff_text="- x", confidence=0.9)
    result = await delayed_writer.maybe_update(llm=llm)
    # Rejected feedback → not in whitelist → nothing should be applied
    assert result["status"] in ("nothing_to_do", "ok")
    assert result.get("patches_applied", []) == []
