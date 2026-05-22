"""Tests for AgentToolExecutor."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mcp_client.agent_tool_executor import (
    AgentBudget,
    AgentToolExecutor,
    BudgetExceeded,
    PermissionDenied,
)
from app.mcp_client.tool_registry import MCPToolRegistry, ToolInfo


def _make_fake_session(tool_result: dict | None = None) -> AsyncMock:
    """Build a mock MCP ClientSession."""
    session = AsyncMock()
    content_item = MagicMock()
    content_item.text = json.dumps(tool_result or {"success": True})
    call_result = MagicMock()
    call_result.isError = False
    call_result.content = [content_item]
    session.call_tool = AsyncMock(return_value=call_result)
    return session


@pytest.mark.asyncio
async def test_call_tool_succeeds_with_permission() -> None:
    registry = MCPToolRegistry()
    tool = ToolInfo("github.get_repo_status", "Get repo status", "github")
    registry.register_tool(tool)
    registry.grant_permission("dev_review", "github.get_repo_status")

    mcp_client = AsyncMock()
    mcp_client.call_tool = AsyncMock(return_value={"status": "ok"})

    executor = AgentToolExecutor("dev_review", mcp_client, registry)
    session = _make_fake_session()

    result = await executor.call_tool(session, "github.get_repo_status", {})
    assert result == {"status": "ok"}


@pytest.mark.asyncio
async def test_call_tool_raises_permission_denied() -> None:
    registry = MCPToolRegistry()
    tool = ToolInfo("github.get_repo_status", "Get repo status", "github")
    registry.register_tool(tool)
    # Don't grant permission for "dev_review"

    mcp_client = AsyncMock()
    executor = AgentToolExecutor("dev_review", mcp_client, registry)
    session = _make_fake_session()

    registry.grant_permission("planning", "github.get_repo_status")

    with pytest.raises(PermissionDenied):
        await executor.call_tool(session, "github.get_repo_status", {})


@pytest.mark.asyncio
async def test_call_tool_raises_when_call_budget_exceeded() -> None:
    registry = MCPToolRegistry()
    tool = ToolInfo("github.get_repo_status", "Get repo status", "github")
    registry.register_tool(tool)
    registry.grant_permission("dev_review", "github.get_repo_status")

    mcp_client = AsyncMock()
    mcp_client.call_tool = AsyncMock(return_value={"status": "ok"})

    budget = AgentBudget(max_calls=2)
    executor = AgentToolExecutor("dev_review", mcp_client, registry, budget=budget)
    session = _make_fake_session()

    # First two calls succeed
    await executor.call_tool(session, "github.get_repo_status", {})
    await executor.call_tool(session, "github.get_repo_status", {})

    # Third call fails
    with pytest.raises(BudgetExceeded, match="call budget"):
        await executor.call_tool(session, "github.get_repo_status", {})


@pytest.mark.asyncio
async def test_call_tool_tracks_call_count() -> None:
    registry = MCPToolRegistry()
    tool = ToolInfo("github.get_repo_status", "Get repo status", "github")
    registry.register_tool(tool)
    registry.grant_permission("dev_review", "github.get_repo_status")

    mcp_client = AsyncMock()
    mcp_client.call_tool = AsyncMock(return_value={"status": "ok"})

    executor = AgentToolExecutor("dev_review", mcp_client, registry)
    session = _make_fake_session()

    assert executor.call_count == 0
    await executor.call_tool(session, "github.get_repo_status", {})
    assert executor.call_count == 1
    await executor.call_tool(session, "github.get_repo_status", {})
    assert executor.call_count == 2


@pytest.mark.asyncio
async def test_call_tool_raises_when_token_budget_exceeded() -> None:
    registry = MCPToolRegistry()
    tool = ToolInfo("github.get_repo_status", "Get repo status", "github")
    registry.register_tool(tool)
    registry.grant_permission("dev_review", "github.get_repo_status")

    mcp_client = AsyncMock()
    # Return a large result
    large_result = {"data": "x" * 100_000}
    mcp_client.call_tool = AsyncMock(return_value=large_result)

    budget = AgentBudget(max_tokens=1000)  # Very small
    executor = AgentToolExecutor("dev_review", mcp_client, registry, budget=budget)
    session = _make_fake_session()

    with pytest.raises(BudgetExceeded, match="token budget"):
        await executor.call_tool(session, "github.get_repo_status", {})


@pytest.mark.asyncio
async def test_call_tool_records_in_registry() -> None:
    registry = MCPToolRegistry()
    tool = ToolInfo("github.get_repo_status", "Get repo status", "github")
    registry.register_tool(tool)
    registry.grant_permission("dev_review", "github.get_repo_status")

    mcp_client = AsyncMock()
    mcp_client.call_tool = AsyncMock(return_value={"status": "ok"})

    executor = AgentToolExecutor("dev_review", mcp_client, registry)
    session = _make_fake_session()

    initial_count = len(registry.call_history["github.get_repo_status"])
    await executor.call_tool(session, "github.get_repo_status", {})
    assert len(registry.call_history["github.get_repo_status"]) == initial_count + 1


def test_get_budget_status_returns_usage() -> None:
    registry = MCPToolRegistry()
    mcp_client = AsyncMock()
    budget = AgentBudget(max_calls=10, max_tokens=50_000, max_time_seconds=300)
    executor = AgentToolExecutor("dev_review", mcp_client, registry, budget=budget)

    status = executor.get_budget_status()
    assert status["calls"]["used"] == 0
    assert status["calls"]["limit"] == 10
    assert status["tokens"]["used"] == 0
    assert status["tokens"]["limit"] == 50_000
    assert "time_seconds" in status


def test_agent_budget_defaults() -> None:
    budget = AgentBudget()
    assert budget.max_calls == 10
    assert budget.max_tokens == 100_000
    assert budget.max_time_seconds == 300.0
