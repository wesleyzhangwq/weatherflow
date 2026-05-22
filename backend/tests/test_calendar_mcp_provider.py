"""Tests for Calendar MCP provider wrapper."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.memory.schemas import ProviderContext
from app.providers.google_calendar_mcp import fetch_calendar_context


def _make_fake_client(search_result: dict) -> Any:
    client_instance = AsyncMock()
    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=None)
    client_instance.call_tool = AsyncMock(return_value=search_result)

    class FakeContextManager:
        async def __aenter__(self):
            return client_instance

        async def __aexit__(self, *args):
            return None

    return FakeContextManager()


async def test_fetch_calendar_context_maps_events_to_provider_context(monkeypatch) -> None:
    search_result = {
        "events": [
            {
                "id": "ev1",
                "title": "Product sync",
                "start": "2026-05-17T10:00:00+08:00",
                "end": "2026-05-17T11:00:00+08:00",
                "duration_minutes": 60,
                "category": "sync",
            },
            {
                "id": "ev2",
                "title": "Focus day",
                "start": "2026-05-18",
                "end": "2026-05-19",
                "duration_minutes": 0,
                "category": "meeting",
            },
        ],
        "coverage": {"calendar_id": "primary", "event_count": 2},
    }

    fake_cm = _make_fake_client(search_result)

    import app.providers.google_calendar_mcp as cm_mod

    class FakeMCPToolClient:
        def __init__(self, *args, **kwargs):
            pass

        def session(self):
            return fake_cm

        async def call_tool(self, session, name, args):
            return search_result

    monkeypatch.setattr(cm_mod, "MCPToolClient", FakeMCPToolClient)

    context = await fetch_calendar_context(
        calendar_id="primary",
        window_days=7,
        mcp_command="echo dummy",
    )

    assert isinstance(context, ProviderContext)
    assert context.source == "google_calendar"
    assert context.status == "success"
    assert context.signals["meeting_count"] == 2
    assert context.signals["meeting_hours"] == 1.0
    assert context.coverage == {"calendar_id": "primary", "event_count": 2}


async def test_fetch_calendar_context_shape_matches_direct_provider_semantics(monkeypatch) -> None:
    """ProviderContext shape must be compatible with DevReviewAgent expectations."""
    search_result = {
        "events": [],
        "coverage": {"calendar_id": "primary", "event_count": 0},
    }
    fake_cm = _make_fake_client(search_result)

    import app.providers.google_calendar_mcp as cm_mod

    class FakeMCPToolClient:
        def __init__(self, *args, **kwargs):
            pass

        def session(self):
            return fake_cm

        async def call_tool(self, session, name, args):
            return search_result

    monkeypatch.setattr(cm_mod, "MCPToolClient", FakeMCPToolClient)

    context = await fetch_calendar_context(
        calendar_id="primary",
        window_days=7,
        mcp_command="echo dummy",
    )

    for key in ("meeting_count", "meeting_hours", "after_hours_events", "events"):
        assert key in context.signals, f"Missing signal key: {key}"
    for key in ("calendar_id", "event_count"):
        assert key in context.coverage, f"Missing coverage key: {key}"
