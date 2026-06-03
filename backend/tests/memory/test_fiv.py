"""FIV memory: derivation fan-out + retrieval strategies (ADR-004 D5)."""

from __future__ import annotations

import pytest

from app.memory import event_log
from app.memory.derivations import run_derivations
from app.memory.retrieval import recall_recent, recall_semantic


@pytest.mark.asyncio
async def test_run_derivations_fans_out_to_projector_and_dmw(monkeypatch):
    """One fan-out drives BOTH mem0 projection (G17) and the DMW, in order."""
    calls: list[str] = []

    async def fake_project(since=None, user_id=None):
        calls.append("project")
        return 0

    async def fake_dmw():
        calls.append("dmw")

    monkeypatch.setattr(
        "app.memory.semantic.projector.project_high_value_events", fake_project
    )
    monkeypatch.setattr("app.memory.delayed_writer.maybe_update", fake_dmw)

    await run_derivations()
    assert calls == ["project", "dmw"]


@pytest.mark.asyncio
async def test_run_derivations_survives_projection_failure(monkeypatch):
    async def boom(since=None, user_id=None):
        raise RuntimeError("qdrant down")

    dmw_ran = []

    async def fake_dmw():
        dmw_ran.append(True)

    monkeypatch.setattr("app.memory.semantic.projector.project_high_value_events", boom)
    monkeypatch.setattr("app.memory.delayed_writer.maybe_update", fake_dmw)

    await run_derivations()  # must not raise
    assert dmw_ran == [True]  # DMW still runs after projection error


def test_recall_recent_marks_feedback_must_keep():
    hyp_id = event_log.append(type="hypothesis", payload={"label": "Flow"})
    event_log.append(
        type="hypothesis_feedback",
        payload={"hypothesis_id": hyp_id, "verdict": "confirmed"},
        refs={"target": hyp_id},
    )
    event_log.append(type="checkin", payload={"weather": "sunny"})

    out = recall_recent("default")
    types = {rec.type for rec, _ in out}
    assert {"hypothesis", "hypothesis_feedback", "checkin"} <= types
    feedback = [(rec, mk) for rec, mk in out if rec.type == "hypothesis_feedback"]
    assert feedback and feedback[0][1] is True  # never truncated (§6.3)


@pytest.mark.asyncio
async def test_recall_semantic_degrades_to_empty(monkeypatch):
    # Empty query short-circuits to [].
    assert await recall_semantic("", "default", 5) == []
    # On any backend failure (mem0/Qdrant down), recall_semantic swallows it.
    import app.memory.semantic.recall as recall_mod

    async def boom(*a, **k):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(recall_mod, "recall_relevant", boom)
    assert await recall_semantic("overload last week", "default", 5) == []
