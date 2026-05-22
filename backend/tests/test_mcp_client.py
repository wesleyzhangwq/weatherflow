"""Tests for MCPToolClient using in-memory fake session."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp_client.client import MCPToolClient


def _make_fake_session(tools: list[dict], tool_result: Any = None, is_error: bool = False) -> Any:
    """Build a mock MCP ClientSession."""
    session = AsyncMock()

    fake_tools = []
    for t in tools:
        tool = MagicMock()
        tool.name = t["name"]
        tool.description = t.get("description", "")
        fake_tools.append(tool)

    list_tools_result = MagicMock()
    list_tools_result.tools = fake_tools
    session.list_tools = AsyncMock(return_value=list_tools_result)

    content_item = MagicMock()
    content_item.text = json.dumps(tool_result) if isinstance(tool_result, dict) else str(tool_result or "")
    call_result = MagicMock()
    call_result.isError = is_error
    call_result.content = [content_item]
    session.call_tool = AsyncMock(return_value=call_result)

    return session


async def test_list_tools_returns_name_and_description() -> None:
    fake_session = _make_fake_session([
        {"name": "github.get_repo_status", "description": "Get repo status"},
        {"name": "github.list_issues", "description": "List issues"},
    ])
    client = MCPToolClient("echo dummy")
    tools = await client.list_tools(fake_session)

    assert len(tools) == 2
    assert tools[0]["name"] == "github.get_repo_status"
    assert tools[1]["name"] == "github.list_issues"


async def test_call_tool_returns_parsed_json() -> None:
    payload = {"repo": "wesleyzhangwq/weatherflow", "open_issues_count": 3}
    fake_session = _make_fake_session([], tool_result=payload)
    client = MCPToolClient("echo dummy")

    result = await client.call_tool(fake_session, "github.get_repo_status", {"owner": "wesleyzhangwq", "repo": "weatherflow"})
    assert result["repo"] == "wesleyzhangwq/weatherflow"
    assert result["open_issues_count"] == 3


async def test_call_tool_raises_on_error_response() -> None:
    fake_session = _make_fake_session([], tool_result="something went wrong", is_error=True)
    client = MCPToolClient("echo dummy")

    with pytest.raises(RuntimeError, match="returned an error"):
        await client.call_tool(fake_session, "github.get_repo_status", {})


async def test_list_tools_raises_on_timeout() -> None:
    session = AsyncMock()
    session.list_tools = AsyncMock(side_effect=asyncio.TimeoutError())

    client = MCPToolClient("echo dummy", timeout=1.0)
    with pytest.raises(RuntimeError, match="timed out"):
        await client.list_tools(session)


async def test_call_tool_raises_on_timeout() -> None:
    session = AsyncMock()
    session.call_tool = AsyncMock(side_effect=asyncio.TimeoutError())

    client = MCPToolClient("echo dummy", timeout=1.0)
    with pytest.raises(RuntimeError, match="timed out"):
        await client.call_tool(session, "github.get_repo_status", {})
