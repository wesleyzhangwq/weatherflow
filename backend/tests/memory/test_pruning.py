"""Hypothesis-card cap: keep only the latest N hypotheses (physical prune)."""

from __future__ import annotations

import pytest

from app.memory import event_log
from app.memory.pruning import prune_hypotheses


@pytest.mark.asyncio
async def test_prune_keeps_latest_n_and_deletes_older():
    ids = [event_log.append(type="hypothesis", payload={"label": "Flow", "n": i}) for i in range(6)]

    removed = await prune_hypotheses(keep=3)
    assert removed == 3  # 6 → keep 3, delete 3 oldest

    remaining = event_log.list_recent(types=["hypothesis"], limit=50)
    assert len(remaining) == 3
    kept = {r.id for r in remaining}
    assert kept == set(ids[3:])  # the 3 newest survive
    for old in ids[:3]:
        assert event_log.get(old) is None


@pytest.mark.asyncio
async def test_prune_cascades_to_feedback():
    h_old = event_log.append(type="hypothesis", payload={"label": "Overload"})
    fb = event_log.append(
        type="hypothesis_feedback",
        payload={"hypothesis_id": h_old, "verdict": "confirmed"},
        refs={"target": h_old},
    )
    for _ in range(3):
        event_log.append(type="hypothesis", payload={"label": "Flow"})

    await prune_hypotheses(keep=3)
    assert event_log.get(h_old) is None
    assert event_log.get(fb) is None  # orphan feedback cascaded away


@pytest.mark.asyncio
async def test_prune_noop_when_under_limit():
    for _ in range(2):
        event_log.append(type="hypothesis", payload={"label": "Steady"})
    assert await prune_hypotheses(keep=3) == 0
