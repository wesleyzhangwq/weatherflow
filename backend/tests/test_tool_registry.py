"""Tests for MCPToolRegistry."""

from __future__ import annotations

import time

import pytest

from app.mcp_client.tool_registry import MCPToolRegistry, ToolInfo, ToolPermission


def test_register_tool_adds_to_tools() -> None:
    registry = MCPToolRegistry()
    tool = ToolInfo(
        name="github.get_repo_status",
        description="Get repository status",
        provider="github",
    )
    registry.register_tool(tool)

    assert "github.get_repo_status" in registry.tools
    assert registry.tools["github.get_repo_status"].description == "Get repository status"


def test_register_permission_sets_allowed_agents() -> None:
    registry = MCPToolRegistry()
    perm = ToolPermission(
        tool_name="github.get_repo_status",
        allowed_agents={"dev_review", "planning"},
    )
    registry.register_permission(perm)

    assert "github.get_repo_status" in registry.permissions
    assert "dev_review" in registry.permissions["github.get_repo_status"].allowed_agents


def test_grant_permission_adds_agent() -> None:
    registry = MCPToolRegistry()
    registry.grant_permission("dev_review", "github.get_repo_status")

    assert "dev_review" in registry.permissions["github.get_repo_status"].allowed_agents


def test_grant_permission_with_rate_limit() -> None:
    registry = MCPToolRegistry()
    registry.grant_permission(
        "dev_review",
        "github.get_repo_status",
        max_calls_per_hour=10,
    )
    perm = registry.permissions["github.get_repo_status"]
    assert perm.max_calls_per_hour == 10


def test_get_available_tools_filters_by_permission() -> None:
    registry = MCPToolRegistry()

    # Register tools
    tool1 = ToolInfo("github.get_repo_status", "Get repo status", "github")
    tool2 = ToolInfo("github.list_issues", "List issues", "github")
    registry.register_tool(tool1)
    registry.register_tool(tool2)

    # Grant permission to only one tool
    registry.grant_permission("dev_review", "github.get_repo_status")

    available = registry.get_available_tools("dev_review")
    assert len(available) == 1
    assert available[0].name == "github.get_repo_status"


def test_can_call_tool_returns_true_if_permitted() -> None:
    registry = MCPToolRegistry()
    tool = ToolInfo("github.get_repo_status", "Get repo status", "github")
    registry.register_tool(tool)
    registry.grant_permission("dev_review", "github.get_repo_status")

    can_call, reason = registry.can_call_tool("dev_review", "github.get_repo_status")
    assert can_call is True
    assert reason == ""


def test_can_call_tool_returns_false_if_not_registered() -> None:
    registry = MCPToolRegistry()

    can_call, reason = registry.can_call_tool("dev_review", "nonexistent.tool")
    assert can_call is False
    assert "not registered" in reason


def test_can_call_tool_returns_false_if_not_permitted() -> None:
    registry = MCPToolRegistry()
    tool = ToolInfo("github.get_repo_status", "Get repo status", "github")
    registry.register_tool(tool)

    # Grant permission only to "planning", not "dev_review"
    registry.grant_permission("planning", "github.get_repo_status")

    can_call, reason = registry.can_call_tool("dev_review", "github.get_repo_status")
    assert can_call is False
    assert "not permitted" in reason


def test_can_call_tool_denies_if_no_permission_configured() -> None:
    registry = MCPToolRegistry()
    tool = ToolInfo("github.get_repo_status", "Get repo status", "github")
    registry.register_tool(tool)
    # Don't explicitly grant permissions — should be denied

    can_call, reason = registry.can_call_tool("any_agent", "github.get_repo_status")
    # Since allowed_agents is empty (not granted), no agent can call
    assert can_call is False


def test_can_call_tool_respects_rate_limit() -> None:
    registry = MCPToolRegistry()
    tool = ToolInfo("github.get_repo_status", "Get repo status", "github")
    registry.register_tool(tool)
    registry.grant_permission(
        "dev_review",
        "github.get_repo_status",
        max_calls_per_hour=2,
    )

    # Record two calls
    registry.record_tool_call("github.get_repo_status")
    registry.record_tool_call("github.get_repo_status")

    # Third call should fail
    can_call, reason = registry.can_call_tool("dev_review", "github.get_repo_status")
    assert can_call is False
    assert "Rate limit exceeded" in reason


def test_record_tool_call_adds_to_history() -> None:
    registry = MCPToolRegistry()
    tool = ToolInfo("github.get_repo_status", "Get repo status", "github")
    registry.register_tool(tool)

    registry.record_tool_call("github.get_repo_status")
    registry.record_tool_call("github.get_repo_status")

    assert len(registry.call_history["github.get_repo_status"]) == 2


def test_rate_limit_clears_old_calls() -> None:
    registry = MCPToolRegistry()
    tool = ToolInfo("github.get_repo_status", "Get repo status", "github")
    registry.register_tool(tool)
    registry.grant_permission(
        "dev_review",
        "github.get_repo_status",
        max_calls_per_hour=2,
    )

    # Record two calls at "old" time
    old_time = time.time() - 3700  # More than 1 hour ago
    registry.call_history["github.get_repo_status"].append(old_time)
    registry.call_history["github.get_repo_status"].append(old_time)

    # New call should be allowed because old calls are outside the 1-hour window
    can_call, reason = registry.can_call_tool("dev_review", "github.get_repo_status")
    assert can_call is True
