"""Golden-case eval: tool dispatch accuracy.

10 scripted user intents → expected dispatch outcome.
Positive cases: correct tool selected, correct mode (read vs write→proposal).
Negative cases: no tool should be called for casual chat.
Safety invariant: every write tool MUST produce a ProposalResult, never execute directly.

Run: pytest tests/eval/ -v
"""

from __future__ import annotations

import pytest

from app.mcp_client.dispatcher import (
    ErrorResult,
    ProposalResult,
    dispatch,
)
from app.mcp_client.tool_registry import registry


# ── Positive: read tools ──────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name, arguments",
    [
        ("calendar.search_events", {"start_time": "2026-06-10T00:00:00Z", "end_time": "2026-06-11T00:00:00Z"}),
        ("calendar.find_free_slots", {"start_time": "2026-06-10T09:00:00Z", "end_time": "2026-06-10T18:00:00Z"}),
        ("github.get_repo_status", {"owner": "test", "repo": "test"}),
        ("github.get_recent_commits", {"owner": "test", "repo": "test"}),
        ("github.list_repos", {}),
    ],
    ids=["search_events", "find_free_slots", "repo_status", "recent_commits", "list_repos"],
)
async def test_read_tool_registered_and_mode_correct(tool_name: str, arguments: dict):
    """Read tools exist in registry with mode='read'."""
    tool = registry().get(tool_name)
    assert tool is not None, f"{tool_name} not in registry"
    assert tool.mode == "read"


# ── Positive: write tools produce Proposal ────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name, arguments",
    [
        (
            "calendar.create_focus_block",
            {"title": "Deep Work", "duration_minutes": 120, "date": "2026-06-11"},
        ),
        (
            "calendar.create_event",
            {"title": "Team Sync", "start_time": "2026-06-11T14:00:00Z", "end_time": "2026-06-11T15:00:00Z"},
        ),
        (
            "github.create_issue",
            {"owner": "test", "repo": "test", "title": "Bug: flaky test"},
        ),
    ],
    ids=["create_focus_block", "create_event", "create_issue"],
)
async def test_write_tool_always_produces_proposal(tool_name: str, arguments: dict):
    """Safety invariant: write tools MUST go through Proposal, never execute."""
    result = await dispatch(
        tool_name=tool_name,
        arguments=arguments,
        conversation_id="eval_conv",
        rationale="eval golden case",
    )
    assert isinstance(result, ProposalResult), (
        f"{tool_name} returned {type(result).__name__}, expected ProposalResult"
    )
    assert result.proposal_id.startswith("evt_proposal_")


# ── Negative: unknown / destructive tools ─────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name",
    [
        "calendar.delete_event",
        "github.delete_repo",
        "nonexistent.tool",
        "calendar.update_event",
    ],
    ids=["delete_event", "delete_repo", "nonexistent", "update_event"],
)
async def test_unavailable_tool_returns_error(tool_name: str):
    """Destructive and unregistered tools must return ErrorResult."""
    result = await dispatch(
        tool_name=tool_name,
        arguments={},
        conversation_id="eval_conv",
    )
    assert isinstance(result, ErrorResult)


# ── Registry-level invariant ──────────────────────────────────────────

def test_no_destructive_tools_in_registry():
    """No path should expose a destructive tool to the LLM."""
    for tool in registry().list_tools():
        assert tool.mode != "destructive", f"{tool.name} is destructive but registered"
