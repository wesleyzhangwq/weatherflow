"""Card-stack derivation rules (ADR D15)."""

from __future__ import annotations

from app.memory import event_log, hypotheses_view


def _seed_hyp(label="Steady", *, source_tag="checkin", conv_id=None):
    cid = event_log.append(type="checkin", payload={"weather": "sunny"})
    payload = {
        "label": label,
        "confidence": 0.5,
        "summary": "s",
        "evidence": [{"text": "x", "source_event_id": cid}],
        "counter_evidence": [],
        "missing_evidence": [],
        "source_tag": source_tag,
    }
    if conv_id:
        payload["conversation_id"] = conv_id
    return event_log.append(type="hypothesis", payload=payload, refs={"triggered_by": cid})


def test_top_three_only():
    ids = [_seed_hyp() for _ in range(5)]
    cards = hypotheses_view.card_stack(limit=3)
    assert len(cards) == 3
    # newest first
    assert cards[0]["id"] == ids[-1]


def test_feedback_removes_from_stack():
    a = _seed_hyp()
    b = _seed_hyp()
    event_log.append(
        type="hypothesis_feedback",
        payload={"hypothesis_id": a, "verdict": "confirmed"},
        refs={"target": a},
    )
    cards = hypotheses_view.card_stack(limit=3)
    assert {c["id"] for c in cards} == {b}


def test_chat_dedupes_per_conversation():
    # Two chat hypotheses in the same conv → only the latest shows
    h1 = _seed_hyp(source_tag="chat", conv_id="conv_X")
    h2 = _seed_hyp(source_tag="chat", conv_id="conv_X")
    h3 = _seed_hyp(source_tag="chat", conv_id="conv_Y")
    cards = hypotheses_view.card_stack(limit=3)
    ids = [c["id"] for c in cards]
    assert h1 not in ids
    assert h2 in ids
    assert h3 in ids
