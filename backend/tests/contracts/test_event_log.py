"""L1 event log invariants (§4.1 / §4.3)."""

from __future__ import annotations


from app.memory import event_log
from app.memory.schemas import CheckinPayload


def test_event_id_has_type_prefix():
    cid = event_log.append(type="checkin", payload=CheckinPayload(weather="sunny").model_dump())
    assert cid.startswith("evt_checkin_")


def test_event_round_trip():
    p = CheckinPayload(weather="rainy", project="wf").model_dump()
    cid = event_log.append(type="checkin", payload=p)
    rec = event_log.get(cid)
    assert rec is not None
    assert rec.type == "checkin"
    assert rec.payload["weather"] == "rainy"
    assert rec.payload["project"] == "wf"


def test_append_is_immutable_no_update_path():
    cid = event_log.append(type="checkin", payload={"weather": "sunny"})
    # The repo deliberately exposes no update/delete API. The contract is
    # enforced by absence — any future regression would surface here.
    assert not hasattr(event_log, "update")
    assert not hasattr(event_log, "delete")
    assert event_log.get(cid) is not None


def test_latest_by_type_orders_desc():
    a = event_log.append(type="checkin", payload={"weather": "sunny"})
    b = event_log.append(type="checkin", payload={"weather": "cloudy"})
    rows = event_log.latest_by_type(["checkin"], limit=5)
    assert rows[0].id == b
    assert rows[1].id == a


def test_find_refs_locates_target():
    h_id = event_log.append(type="hypothesis", payload={"label": "Steady", "confidence": 0.5, "summary": "x", "evidence": [], "source_tag": "checkin"})
    event_log.append(
        type="hypothesis_feedback",
        payload={"hypothesis_id": h_id, "verdict": "confirmed"},
        refs={"target": h_id},
    )
    found = event_log.find_refs(ref_key="target", ref_value=h_id)
    assert len(found) == 1
    assert found[0].type == "hypothesis_feedback"
