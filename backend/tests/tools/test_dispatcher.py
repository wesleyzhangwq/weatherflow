"""Tool dispatcher — read/write/destructive contract (§7.4 + ADR D18, D19)."""

from __future__ import annotations

import pytest

from app.mcp_client import dispatcher as dispatcher_mod
from app.mcp_client.dispatcher import (
    ErrorResult,
    ObservationResult,
    ProposalResult,
    dispatch,
)
from app.mcp_client.tool_registry import registry


@pytest.mark.asyncio
async def test_destructive_tools_are_unreachable():
    # The registry contract: destructive tools are never registered.
    assert all(t.mode != "destructive" for t in registry().list_tools())
    # And a directly-attempted destructive call returns ErrorResult.
    result = await dispatch(
        tool_name="calendar.delete_event",
        arguments={"event_id": "x"},
        conversation_id="conv_test",
    )
    assert isinstance(result, ErrorResult)


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_not_exception():
    result = await dispatch(
        tool_name="nonexistent.tool",
        arguments={},
        conversation_id="conv_test",
    )
    assert isinstance(result, ErrorResult)


@pytest.mark.asyncio
async def test_write_tool_creates_proposal_without_executing(monkeypatch):
    # Stub the MCP client; if a write tool is dispatched we should NOT see
    # a session call.
    called = {"calls": 0}

    class _NeverCalled:
        def __init__(self, *a, **kw): ...
        def session(self):  # pragma: no cover
            called["calls"] += 1
            raise AssertionError("Write tools must not run the MCP")

    monkeypatch.setattr(dispatcher_mod, "MCPToolClient", _NeverCalled)

    result = await dispatch(
        tool_name="calendar.create_focus_block",
        arguments={"title": "deep work", "duration_minutes": 90, "date": "2026-05-26"},
        conversation_id="conv_test",
        rationale="user looks Overload-ish",
    )
    assert isinstance(result, ProposalResult)
    assert result.proposal_id.startswith("evt_proposal_")
    assert called["calls"] == 0


@pytest.mark.asyncio
async def test_read_tool_writes_tool_call_event(monkeypatch):
    captured: dict = {}

    class _StubClient:
        def __init__(self, *a, **kw): ...
        def session(self):
            return _StubSession()

        async def call_tool(self, session, name, args):  # pragma: no cover
            raise AssertionError("read path uses session context manager")

    class _StubSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None

    class _StubMCPClient:
        def __init__(self, *a, **kw): ...
        def session(self):
            class _Ctx:
                async def __aenter__(_self): return object()
                async def __aexit__(_self, *a): return None
            return _Ctx()

        async def call_tool(self, session, name, args):
            captured["called"] = (name, args)
            return {"events": [{"start": "x", "summary": "y"}]}

    monkeypatch.setattr(dispatcher_mod, "MCPToolClient", _StubMCPClient)

    result = await dispatch(
        tool_name="calendar.search_events",
        arguments={"start_time": "a", "end_time": "b"},
        conversation_id="conv_test",
    )
    assert isinstance(result, ObservationResult)
    assert captured["called"][0] == "calendar.search_events"
    # The event was written
    from app.memory import event_log
    rec = event_log.get(result.tool_call_event_id)
    assert rec is not None
    assert rec.type == "tool_call"
    assert rec.payload["tool_name"] == "calendar.search_events"
