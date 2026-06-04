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
    # append stays immutable: there is no in-place UPDATE path (status is always
    # derived from later events). `delete` is the ONE sanctioned exception — it
    # exists only for the hypothesis-card cap (see DECISIONS-v2) and is otherwise
    # off-limits; it must never be used to "update" an event.
    assert not hasattr(event_log, "update")
    assert event_log.get(cid) is not None


def test_delete_removes_rows_and_is_scoped():
    a = event_log.append(type="hypothesis", payload={"label": "Flow"})
    b = event_log.append(type="hypothesis", payload={"label": "Steady"})
    n = event_log.delete([a])
    assert n == 1
    assert event_log.get(a) is None
    assert event_log.get(b) is not None  # only the targeted row is removed
    assert event_log.delete([]) == 0


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
