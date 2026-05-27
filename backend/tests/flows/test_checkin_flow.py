"""T1 Check-in end-to-end flow (§12.1)."""

from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.core import llm as llm_module
from app.main import create_app


GOOD_HYP_JSON_TEMPLATE = (
    '{{"label": "Steady", "confidence": 0.6, "summary": "平稳推进。", '
    '"evidence": [{{"text": "今天的 check-in", "source_event_id": "{eid}"}}], '
    '"counter_evidence": [], "missing_evidence": []}}'
)


class _ScriptedLLM:
    """LLM that produces a hypothesis referencing the most-recent checkin id."""

    def __init__(self):
        from app.memory import event_log

        self._event_log = event_log
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        # The most recent checkin must be the trigger; reference it.
        cks = self._event_log.latest_by_type(["checkin"], limit=1)
        eid = cks[0].id if cks else "evt_checkin_unknown"
        return GOOD_HYP_JSON_TEMPLATE.format(eid=eid)

    async def embed(self, texts, **kw):
        return [[0.0] * 4 for _ in texts]

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_checkin_persists_event_and_returns_hypothesis(monkeypatch):
    stub = _ScriptedLLM()
    monkeypatch.setattr(llm_module, "build_llm_client", lambda *_a, **_kw: stub)
    monkeypatch.setattr(main_module, "build_llm_client", lambda *_a, **_kw: stub)
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/checkin",
            json={"weather": "cloudy", "project": "wf", "friction_point": "context_switch"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["checkin_id"].startswith("evt_checkin_")
        assert body["hypothesis_id"].startswith("evt_hypothesis_")
        assert body["hypothesis"]["label"] == "Steady"

        # main-page stack now has 1 card
        list_resp = client.get("/api/hypotheses?limit=3")
        assert list_resp.status_code == 200
        cards = list_resp.json()
        assert len(cards) == 1
        assert cards[0]["id"] == body["hypothesis_id"]


@pytest.mark.asyncio
async def test_feedback_drops_card_from_stack(monkeypatch):
    stub = _ScriptedLLM()
    monkeypatch.setattr(llm_module, "build_llm_client", lambda *_a, **_kw: stub)
    monkeypatch.setattr(main_module, "build_llm_client", lambda *_a, **_kw: stub)
    app = create_app()
    with TestClient(app) as client:
        check_resp = client.post("/api/checkin", json={"weather": "rainy"})
        hyp_id = check_resp.json()["hypothesis_id"]
        # Calibrate as confirmed
        fb_resp = client.post(
            f"/api/hypotheses/{hyp_id}/feedback", json={"verdict": "confirmed"}
        )
        assert fb_resp.status_code == 200
        # main-page stack should now be empty
        cards = client.get("/api/hypotheses?limit=3").json()
        assert cards == []
        # but history retains it with status=confirmed
        history = client.get("/api/hypotheses/history").json()
        assert history[0]["status"] == "confirmed"
