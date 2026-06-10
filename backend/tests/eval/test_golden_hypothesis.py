"""Golden-case eval: hypothesis generation quality.

Tests source_event_id traceability (the hard invariant) and label/schema
conformance. Uses StubLLM with canned responses — no real LLM calls.

Two tracks:
  1. Valid hypothesis → accepted, all evidence source_event_ids in bundle.
  2. Invalid hypothesis (fabricated IDs, bad label) → rejected or falls back.
"""

from __future__ import annotations

import json

import pytest

from app.agents.rhythm_agent import RhythmAgent
from app.memory.schemas import (
    BundleEntry,
    EvidenceBundle,
    HypothesisPayload,
)


class _FixedLLM:
    def __init__(self, payload: dict):
        self._payload = payload

    async def chat(self, messages, **kw):
        return json.dumps(self._payload)

    async def aclose(self):
        return None

    async def embed(self, texts, **kw):
        return [[0.0] for _ in texts]


def _bundle(*event_ids: str, mode: str = "checkin") -> EvidenceBundle:
    return EvidenceBundle(
        trigger_event_id=event_ids[0],
        entries=[
            BundleEntry(event_id=eid, event_type="checkin", rendered=f"event {eid}")
            for eid in event_ids
        ],
        mode=mode,
    )


# ── Track 1: Valid hypotheses accepted ────────────────────────────────

_VALID_CASES = [
    {
        "id": "flow_single_evidence",
        "bundle_ids": ["evt_checkin_001"],
        "llm_response": {
            "label": "Flow",
            "confidence": 0.85,
            "summary": "高效心流状态",
            "evidence": [{"text": "连续提交 4 小时", "source_event_id": "evt_checkin_001"}],
            "counter_evidence": [],
            "missing_evidence": [],
        },
        "expect_label": "Flow",
    },
    {
        "id": "overload_multi_evidence",
        "bundle_ids": ["evt_checkin_010", "evt_github_011", "evt_calendar_012"],
        "llm_response": {
            "label": "Overload",
            "confidence": 0.72,
            "summary": "任务堆积，注意力分散",
            "evidence": [
                {"text": "6 个会议", "source_event_id": "evt_calendar_012"},
                {"text": "PR 积压", "source_event_id": "evt_github_011"},
            ],
            "counter_evidence": [
                {"text": "仍有提交", "source_event_id": "evt_checkin_010"},
            ],
            "missing_evidence": ["sleep data"],
        },
        "expect_label": "Overload",
    },
    {
        "id": "recovery_low_confidence",
        "bundle_ids": ["evt_checkin_020"],
        "llm_response": {
            "label": "Recovery",
            "confidence": 0.35,
            "summary": "信号偏弱，初步判定恢复",
            "evidence": [{"text": "半天无提交", "source_event_id": "evt_checkin_020"}],
            "counter_evidence": [],
            "missing_evidence": ["calendar data"],
        },
        "expect_label": "Recovery",
    },
    {
        "id": "fragmented_with_counter",
        "bundle_ids": ["evt_checkin_030", "evt_github_031"],
        "llm_response": {
            "label": "Fragmented",
            "confidence": 0.60,
            "summary": "频繁切换上下文",
            "evidence": [{"text": "5 个 repo 切换", "source_event_id": "evt_github_031"}],
            "counter_evidence": [{"text": "完成了 1 个 PR", "source_event_id": "evt_checkin_030"}],
            "missing_evidence": [],
        },
        "expect_label": "Fragmented",
    },
    {
        "id": "blocked_minimal",
        "bundle_ids": ["evt_checkin_040"],
        "llm_response": {
            "label": "Blocked",
            "confidence": 0.50,
            "summary": "外部阻塞中",
            "evidence": [{"text": "trigger event", "source_event_id": "evt_checkin_040"}],
            "counter_evidence": [],
            "missing_evidence": [],
        },
        "expect_label": "Blocked",
    },
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _VALID_CASES, ids=[c["id"] for c in _VALID_CASES])
async def test_valid_hypothesis_accepted(case: dict):
    bundle = _bundle(*case["bundle_ids"])
    llm = _FixedLLM(case["llm_response"])
    agent = RhythmAgent(llm)

    payload = await agent.generate(bundle=bundle, mode="checkin")

    assert isinstance(payload, HypothesisPayload)
    assert payload.label == case["expect_label"]
    assert 0.0 <= payload.confidence <= 1.0
    assert len(payload.evidence) >= 1

    valid_ids = bundle.all_event_ids()
    for ev in [*payload.evidence, *payload.counter_evidence]:
        assert ev.source_event_id in valid_ids, (
            f"evidence references {ev.source_event_id} not in bundle {valid_ids}"
        )


# ── Track 2: Invalid hypotheses → fallback ───────────────────────────

_INVALID_CASES = [
    {
        "id": "fabricated_source_event_id",
        "bundle_ids": ["evt_checkin_100"],
        "llm_response": {
            "label": "Flow",
            "confidence": 0.9,
            "summary": "OK",
            "evidence": [{"text": "fake", "source_event_id": "evt_DOES_NOT_EXIST"}],
            "counter_evidence": [],
            "missing_evidence": [],
        },
    },
    {
        "id": "empty_evidence_array",
        "bundle_ids": ["evt_checkin_110"],
        "llm_response": {
            "label": "Steady",
            "confidence": 0.5,
            "summary": "empty",
            "evidence": [],
            "counter_evidence": [],
            "missing_evidence": [],
        },
    },
    {
        "id": "counter_evidence_fabricated",
        "bundle_ids": ["evt_checkin_120"],
        "llm_response": {
            "label": "Recovery",
            "confidence": 0.4,
            "summary": "bad counter",
            "evidence": [{"text": "ok", "source_event_id": "evt_checkin_120"}],
            "counter_evidence": [{"text": "bad", "source_event_id": "evt_FAKE"}],
            "missing_evidence": [],
        },
    },
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _INVALID_CASES, ids=[c["id"] for c in _INVALID_CASES])
async def test_invalid_hypothesis_triggers_fallback(case: dict):
    bundle = _bundle(*case["bundle_ids"])
    llm = _FixedLLM(case["llm_response"])
    agent = RhythmAgent(llm)

    payload = await agent.generate(bundle=bundle, mode="checkin")

    assert payload.label == "Steady"
    assert payload.confidence == 0.3
    for ev in payload.evidence:
        assert ev.source_event_id in bundle.all_event_ids()


# ── Schema conformance: all 6 labels accepted ────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["Flow", "Recovery", "Steady", "Overload", "Blocked", "Fragmented"])
async def test_all_six_labels_accepted(label: str):
    bundle = _bundle("evt_checkin_200")
    response = {
        "label": label,
        "confidence": 0.5,
        "summary": f"test {label}",
        "evidence": [{"text": "x", "source_event_id": "evt_checkin_200"}],
        "counter_evidence": [],
        "missing_evidence": [],
    }
    llm = _FixedLLM(response)
    agent = RhythmAgent(llm)
    payload = await agent.generate(bundle=bundle, mode="checkin")
    assert payload.label == label
