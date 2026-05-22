"""Tests for the actions API router."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.memory.schemas import ActionProposal
from app.routers.actions import _PROPOSALS


@pytest.fixture(autouse=True)
def _clear_proposals():
    _PROPOSALS.clear()
    yield
    _PROPOSALS.clear()


client = TestClient(app)


def _create_proposal(**kwargs) -> dict:
    defaults = dict(
        kind="focus_block",
        title="Deep Work: memory refactor",
        rationale="User named a concrete work item",
        tool_name="calendar.create_focus_block",
        tool_arguments={"title": "Deep Work: memory refactor", "duration_minutes": 90},
    )
    defaults.update(kwargs)
    resp = client.post("/api/actions/proposals", json=defaults)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_get_proposal() -> None:
    created = _create_proposal()
    pid = created["id"]

    resp = client.get(f"/api/actions/proposals/{pid}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Deep Work: memory refactor"


def test_get_nonexistent_proposal_returns_404() -> None:
    resp = client.get("/api/actions/proposals/nonexistent-id")
    assert resp.status_code == 404


def test_execute_without_confirmation_returns_400() -> None:
    created = _create_proposal()
    pid = created["id"]
    resp = client.post(f"/api/actions/{pid}/execute", json={"confirmed": False})
    assert resp.status_code == 400
    assert "confirmation" in resp.json()["detail"].lower()


def test_execute_nonexistent_proposal_returns_404() -> None:
    resp = client.post("/api/actions/no-such-id/execute", json={"confirmed": True})
    assert resp.status_code == 404
