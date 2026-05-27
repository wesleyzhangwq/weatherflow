"""Hard contracts from architecture-v1.md §4.2 — Hypothesis payload shape."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.memory.schemas import EvidenceItem, HypothesisPayload


def test_label_must_be_in_vocabulary():
    with pytest.raises(ValidationError):
        HypothesisPayload(
            label="NotARealLabel",  # type: ignore[arg-type]
            confidence=0.5,
            summary="s",
            evidence=[EvidenceItem(text="x", source_event_id="evt_checkin_x")],
            source_tag="checkin",
        )


def test_confidence_must_be_in_unit_interval():
    with pytest.raises(ValidationError):
        HypothesisPayload(
            label="Flow",
            confidence=1.5,
            summary="s",
            evidence=[EvidenceItem(text="x", source_event_id="evt_checkin_x")],
            source_tag="checkin",
        )


def test_evidence_cannot_be_empty():
    with pytest.raises(ValidationError):
        HypothesisPayload(
            label="Steady",
            confidence=0.5,
            summary="s",
            evidence=[],
            source_tag="checkin",
        )


def test_each_evidence_item_requires_source_event_id():
    with pytest.raises(ValidationError):
        EvidenceItem(text="t")  # type: ignore[call-arg]


def test_source_tag_enum():
    with pytest.raises(ValidationError):
        HypothesisPayload(
            label="Flow",
            confidence=0.5,
            summary="s",
            evidence=[EvidenceItem(text="x", source_event_id="evt_checkin_x")],
            source_tag="weekly",  # type: ignore[arg-type]
        )


def test_valid_hypothesis_round_trips():
    h = HypothesisPayload(
        label="Overload",
        confidence=0.72,
        summary="过载",
        evidence=[EvidenceItem(text="过去 3 天有 12 场会议", source_event_id="evt_calendar_x")],
        counter_evidence=[EvidenceItem(text="GitHub 仍有推进", source_event_id="evt_github_y")],
        missing_evidence=["明天日历"],
        source_tag="scheduled",
    )
    dumped = h.model_dump()
    again = HypothesisPayload.model_validate(dumped)
    assert again.label == "Overload"
    assert again.evidence[0].source_event_id == "evt_calendar_x"
