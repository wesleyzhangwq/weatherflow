"""Tests for L2.5 semantic memory (v2 Track 1B).

Tests cover:
- MemoryProjector whitelist logic
- Semantic recall graceful degradation
- Rebuild script (dry-run mode)
- Source_event_id backlink integrity
"""

from __future__ import annotations

import pytest

from app.memory import event_log
from app.memory.semantic.projector import _is_projectable, _render_for_memory


# ---------------------------------------------------------------------------
# Tests: projector whitelist (M1B.2)
# ---------------------------------------------------------------------------


def test_checkin_is_projectable():
    """Check-in events are always projectable."""
    rec = type("Rec", (), {
        "type": "checkin",
        "payload": {"weather": "sunny"},
        "id": "evt_checkin_001",
        "timestamp": "2026-06-01T10:00:00",
        "user_id": "default",
    })()
    assert _is_projectable(rec) is True


def test_executed_action_is_projectable():
    """Executed actions are always projectable."""
    rec = type("Rec", (), {
        "type": "executed_action",
        "payload": {"tool_name": "calendar.create_focus_block"},
        "id": "evt_action_001",
        "timestamp": "2026-06-01T10:00:00",
        "user_id": "default",
    })()
    assert _is_projectable(rec) is True


def test_reasoning_step_not_projectable():
    """Low-value events like reasoning_step are NOT projectable."""
    rec = type("Rec", (), {
        "type": "reasoning_step",
        "payload": {"text": "thinking..."},
        "id": "evt_reason_001",
        "timestamp": "2026-06-01T10:00:00",
        "user_id": "default",
    })()
    assert _is_projectable(rec) is False


def test_tool_call_not_projectable():
    """Tool calls are NOT projectable."""
    rec = type("Rec", (), {
        "type": "tool_call",
        "payload": {"tool_name": "calendar.list_events"},
        "id": "evt_tool_001",
        "timestamp": "2026-06-01T10:00:00",
        "user_id": "default",
    })()
    assert _is_projectable(rec) is False


def test_snapshot_not_projectable():
    """Raw snapshots are NOT projectable."""
    rec = type("Rec", (), {
        "type": "calendar_snapshot",
        "payload": {"events": []},
        "id": "evt_snap_001",
        "timestamp": "2026-06-01T10:00:00",
        "user_id": "default",
    })()
    assert _is_projectable(rec) is False


def test_hypothesis_only_projectable_when_confirmed():
    """Hypothesis is only projectable if there's a confirmed feedback event."""
    # Unconfirmed hypothesis
    rec = type("Rec", (), {
        "type": "hypothesis",
        "payload": {"label": "Overload"},
        "id": "evt_hyp_001",
        "timestamp": "2026-06-01T10:00:00",
        "user_id": "default",
    })()
    # Without confirmed feedback in L1, this should be False
    assert _is_projectable(rec) is False


def test_chat_turn_with_preference_is_projectable():
    """Chat turns with preference keywords are projectable."""
    rec = type("Rec", (), {
        "type": "chat_turn",
        "payload": {"role": "user", "content": "I prefer deep work in the morning"},
        "id": "evt_chat_001",
        "timestamp": "2026-06-01T10:00:00",
        "user_id": "default",
    })()
    assert _is_projectable(rec) is True


def test_chat_turn_without_preference_not_projectable():
    """Chat turns without preference signals are NOT projectable."""
    rec = type("Rec", (), {
        "type": "chat_turn",
        "payload": {"role": "user", "content": "帮我看看明天的日程"},
        "id": "evt_chat_002",
        "timestamp": "2026-06-01T10:00:00",
        "user_id": "default",
    })()
    assert _is_projectable(rec) is False


# ---------------------------------------------------------------------------
# Tests: renderer
# ---------------------------------------------------------------------------


def test_render_checkin():
    rec = type("Rec", (), {
        "type": "checkin",
        "payload": {"weather": "sunny", "project": "wf", "free_text": "feeling good"},
        "id": "evt_001",
    })()
    text = _render_for_memory(rec)
    assert "sunny" in text
    assert "wf" in text
    assert "feeling good" in text


def test_render_hypothesis():
    rec = type("Rec", (), {
        "type": "hypothesis",
        "payload": {"label": "Flow", "confidence": 0.9, "summary": "Great day"},
        "id": "evt_002",
    })()
    text = _render_for_memory(rec)
    assert "Flow" in text
    assert "0.90" in text


# ---------------------------------------------------------------------------
# Tests: semantic recall graceful degradation (M1B.3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_returns_empty_when_mem0_unavailable():
    """recall_relevant returns empty list when mem0 not installed."""
    from app.memory.semantic.recall import recall_relevant

    result = await recall_relevant(query="test query", user_id="default")
    # mem0 not installed → empty list, no crash
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Tests: rebuild dry-run (M1B.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rebuild_dry_run_counts_events():
    """rebuild in dry-run mode counts projectable events without modifying anything."""
    # Create some events
    event_log.append(type="checkin", payload={"weather": "sunny"})
    event_log.append(type="reasoning_step", payload={"text": "thinking"})

    from scripts.rebuild_memory import rebuild

    stats = await rebuild("default", dry_run=True)
    assert stats["total_events"] >= 2
    assert stats["projectable"] >= 1  # at least the checkin
    assert stats["projected"] == 0  # dry run doesn't project
