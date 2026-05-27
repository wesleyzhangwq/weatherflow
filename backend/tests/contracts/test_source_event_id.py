"""§4.3 hard invariant: every evidence MUST point at an event that exists.

Validation is enforced in app.agents.rhythm_agent during the parse step.
This test exercises that path directly.
"""

from __future__ import annotations

import json
import pytest

from app.agents.rhythm_agent import RhythmAgent
from app.memory.schemas import BundleEntry, EvidenceBundle


class _FixedLLM:
    """LLM stub that returns a JSON string regardless of input."""

    def __init__(self, payload: dict):
        self._payload = payload

    async def chat(self, messages, **kw):
        return json.dumps(self._payload)

    async def aclose(self):
        return None

    async def embed(self, texts, **kw):
        return [[0.0] for _ in texts]


def _bundle(*event_ids: str) -> EvidenceBundle:
    return EvidenceBundle(
        trigger_event_id=event_ids[0],
        entries=[
            BundleEntry(event_id=eid, event_type="checkin", rendered=f"e {eid}")
            for eid in event_ids
        ],
        mode="checkin",
    )


@pytest.mark.asyncio
async def test_unknown_source_event_id_triggers_fallback():
    bundle = _bundle("evt_checkin_real")
    bogus = {
        "label": "Flow",
        "confidence": 0.9,
        "summary": "OK",
        "evidence": [{"text": "x", "source_event_id": "evt_checkin_fake"}],
        "counter_evidence": [],
        "missing_evidence": [],
    }
    llm = _FixedLLM(bogus)
    agent = RhythmAgent(llm)
    payload = await agent.generate(bundle=bundle, mode="checkin")
    # Two retries fail; fallback returns trigger-only evidence
    assert payload.label == "Steady"
    assert payload.evidence[0].source_event_id == "evt_checkin_real"


@pytest.mark.asyncio
async def test_valid_source_event_id_is_accepted():
    bundle = _bundle("evt_checkin_real")
    good = {
        "label": "Recovery",
        "confidence": 0.4,
        "summary": "节奏轻",
        "evidence": [{"text": "x", "source_event_id": "evt_checkin_real"}],
        "counter_evidence": [],
        "missing_evidence": [],
    }
    llm = _FixedLLM(good)
    agent = RhythmAgent(llm)
    payload = await agent.generate(bundle=bundle, mode="checkin")
    assert payload.label == "Recovery"
    assert payload.evidence[0].source_event_id == "evt_checkin_real"
