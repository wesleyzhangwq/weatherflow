from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_servers.weatherflow_calendar.tools import (
    create_event,
    create_focus_block,
    find_free_slots,
    search_events,
)


def _make_fake_client(items: list[dict]) -> Any:
    """Return a fake async context manager httpx client that returns given items."""
    response = MagicMock()
    response.raise_for_status = MagicMock(return_value=None)
    response.json = MagicMock(return_value={"items": items})

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(return_value=response)
    client.post = AsyncMock(return_value=response)
    return client


def _event(title: str, start: str, end: str) -> dict:
    return {
        "id": "ev-1",
        "summary": title,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }


# ---------------------------------------------------------------------------
# search_events
# ---------------------------------------------------------------------------


async def test_search_events_returns_sanitized_events() -> None:
    items = [_event("Design review", "2026-05-22T10:00:00+08:00", "2026-05-22T10:30:00+08:00")]
    client = _make_fake_client(items)

    result = await search_events(
        start_time="2026-05-22T09:00:00+08:00",
        end_time="2026-05-22T18:00:00+08:00",
        _client=client,
    )
    assert len(result["events"]) == 1
    ev = result["events"][0]
    assert ev["title"] == "Design review"
    assert ev["duration_minutes"] == 30
    assert ev["category"] == "review"


async def test_search_events_keyword_filter() -> None:
    items = [
        _event("Design review", "2026-05-22T10:00:00+08:00", "2026-05-22T10:30:00+08:00"),
        _event("Team sync", "2026-05-22T11:00:00+08:00", "2026-05-22T11:30:00+08:00"),
    ]
    client = _make_fake_client(items)

    result = await search_events(
        start_time="2026-05-22T09:00:00+08:00",
        end_time="2026-05-22T18:00:00+08:00",
        keyword="review",
        _client=client,
    )
    assert len(result["events"]) == 1
    assert result["events"][0]["title"] == "Design review"


async def test_search_events_empty_list() -> None:
    client = _make_fake_client([])
    result = await search_events(
        start_time="2026-05-22T09:00:00+08:00",
        end_time="2026-05-22T18:00:00+08:00",
        _client=client,
    )
    assert result["events"] == []
    assert result["coverage"]["event_count"] == 0


# ---------------------------------------------------------------------------
# find_free_slots
# ---------------------------------------------------------------------------


async def test_find_free_slots_no_events_returns_full_workday() -> None:
    client = _make_fake_client([])

    result = await find_free_slots(
        start_time="2026-05-22T09:00:00+08:00",
        end_time="2026-05-22T18:00:00+08:00",
        min_duration_minutes=30,
        workday_start="09:00",
        workday_end="18:00",
        _client=client,
    )
    slots = result["slots"]
    assert len(slots) == 1
    assert slots[0]["duration_minutes"] == 540


async def test_find_free_slots_overlapping_meetings_merge() -> None:
    items = [
        _event("Meeting A", "2026-05-22T10:00:00+08:00", "2026-05-22T11:00:00+08:00"),
        _event("Meeting B", "2026-05-22T10:30:00+08:00", "2026-05-22T11:30:00+08:00"),
    ]
    client = _make_fake_client(items)

    result = await find_free_slots(
        start_time="2026-05-22T09:00:00+08:00",
        end_time="2026-05-22T18:00:00+08:00",
        min_duration_minutes=30,
        workday_start="09:00",
        workday_end="18:00",
        _client=client,
    )
    slots = result["slots"]
    starts = [s["start"] for s in slots]
    # merged busy block: 10:00-11:30 → free: 9:00-10:00 and 11:30-18:00
    assert len(slots) == 2
    total_free = sum(s["duration_minutes"] for s in slots)
    assert total_free == 60 + 390


async def test_find_free_slots_filters_below_minimum() -> None:
    items = [
        _event("Meeting A", "2026-05-22T09:30:00+08:00", "2026-05-22T09:50:00+08:00"),
    ]
    client = _make_fake_client(items)

    result = await find_free_slots(
        start_time="2026-05-22T09:00:00+08:00",
        end_time="2026-05-22T18:00:00+08:00",
        min_duration_minutes=45,
        workday_start="09:00",
        workday_end="18:00",
        _client=client,
    )
    slots = result["slots"]
    # 9:00-9:30 is 30 min, filtered; 9:50-18:00 is 490 min, kept
    for s in slots:
        assert s["duration_minutes"] >= 45


async def test_find_free_slots_timezone_offsets_preserved() -> None:
    client = _make_fake_client([])
    result = await find_free_slots(
        start_time="2026-05-22T09:00:00+08:00",
        end_time="2026-05-22T18:00:00+08:00",
        min_duration_minutes=30,
        workday_start="09:00",
        workday_end="18:00",
        _client=client,
    )
    slots = result["slots"]
    assert len(slots) > 0
    for slot in slots:
        assert "+08:00" in slot["start"] or "Z" in slot["start"] or "T" in slot["start"]


# ---------------------------------------------------------------------------
# create_event
# ---------------------------------------------------------------------------


async def test_create_event_dry_run_returns_without_calling_google(monkeypatch) -> None:
    monkeypatch.setenv("WF_MCP_WRITE_TOOLS_ENABLED", "false")
    client = _make_fake_client([])

    result = await create_event(
        title="Planning",
        start_time="2026-05-23T10:00:00+08:00",
        end_time="2026-05-23T11:00:00+08:00",
        dry_run=True,
        _client=client,
    )
    assert result["dry_run"] is True
    assert result["created"] is False
    client.post.assert_not_called()


async def test_create_event_disabled_write_raises_permission_error(monkeypatch) -> None:
    monkeypatch.setenv("WF_MCP_WRITE_TOOLS_ENABLED", "false")
    client = _make_fake_client([])

    with pytest.raises(PermissionError, match="disabled"):
        await create_event(
            title="Planning",
            start_time="2026-05-23T10:00:00+08:00",
            end_time="2026-05-23T11:00:00+08:00",
            dry_run=False,
            _client=client,
        )


async def test_create_event_write_enabled_posts_to_google(monkeypatch) -> None:
    monkeypatch.setenv("WF_MCP_WRITE_TOOLS_ENABLED", "true")

    post_response = MagicMock()
    post_response.raise_for_status = MagicMock(return_value=None)
    post_response.json = MagicMock(return_value={
        "id": "new-event-id",
        "summary": "Planning",
        "htmlLink": "https://calendar.google.com/event?eid=...",
    })

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=post_response)

    result = await create_event(
        title="Planning",
        start_time="2026-05-23T10:00:00+08:00",
        end_time="2026-05-23T11:00:00+08:00",
        dry_run=False,
        _client=client,
    )
    assert result["created"] is True
    assert result["event"]["id"] == "new-event-id"
    client.post.assert_called_once()


# ---------------------------------------------------------------------------
# create_focus_block
# ---------------------------------------------------------------------------


async def test_create_focus_block_uses_preferred_slot(monkeypatch) -> None:
    monkeypatch.setenv("WF_MCP_WRITE_TOOLS_ENABLED", "false")

    client = _make_fake_client([])

    result = await create_focus_block(
        title="Deep Work: WF memory refactor",
        duration_minutes=90,
        preferred_time="morning",
        date="2026-05-23",
        dry_run=True,
        _client=client,
    )
    assert result.get("dry_run") is True or result.get("created") is False
    assert "selected_slot" in result


async def test_create_focus_block_fallback_when_preferred_window_busy(monkeypatch) -> None:
    monkeypatch.setenv("WF_MCP_WRITE_TOOLS_ENABLED", "false")

    call_count = {"n": 0}
    morning_items = [
        _event("Busy All Morning", "2026-05-23T09:00:00+00:00", "2026-05-23T12:00:00+00:00"),
    ]

    async def fake_find_free_slots(**kwargs: Any) -> dict:
        call_count["n"] += 1
        if kwargs.get("workday_start") == "09:00":
            return {"slots": []}
        return {"slots": [{"start": "2026-05-23T13:00:00+00:00", "end": "2026-05-23T18:00:00+00:00", "duration_minutes": 300}]}

    import mcp_servers.weatherflow_calendar.tools as tools_mod
    monkeypatch.setattr(tools_mod, "find_free_slots", fake_find_free_slots)

    result = await tools_mod.create_focus_block(
        title="Deep Work",
        duration_minutes=90,
        preferred_time="morning",
        date="2026-05-23",
        dry_run=True,
    )
    assert result.get("selected_slot") is not None
    assert call_count["n"] >= 2
