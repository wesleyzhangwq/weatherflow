"""Tests for GitHub MCP provider wrapper."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.memory.schemas import ProviderContext
from app.providers.github_mcp import fetch_github_context


def _make_fake_client(
    status_result: dict,
    commits_result: dict,
) -> Any:
    client_instance = AsyncMock()
    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=None)

    call_count = {"n": 0}
    results = [status_result, commits_result]

    async def fake_call_tool(session, name, args):
        idx = call_count["n"]
        call_count["n"] += 1
        return results[min(idx, len(results) - 1)]

    client_instance.call_tool = fake_call_tool

    class FakeContextManager:
        async def __aenter__(self):
            return client_instance

        async def __aexit__(self, *args):
            return None

    return FakeContextManager()


async def test_fetch_github_context_returns_provider_context_shape(monkeypatch) -> None:
    status = {
        "repo": "wesleyzhangwq/weatherflow",
        "default_branch": "main",
        "latest_commit": {"sha": "abc123", "message": "Update docs", "committed_at": "2026-05-22T08:30:00Z"},
        "open_issues_count": 4,
        "open_prs_count": 1,
        "recent_activity": [
            {"type": "commit", "title": "Update docs", "at": "2026-05-22T08:30:00Z"}
        ],
    }
    commits = {
        "commits": [
            {"sha": "abc123", "message": "Update docs", "author": "Wesley", "committed_at": "2026-05-22T08:30:00Z"},
            {"sha": "def456", "message": "Fix tests", "author": "Wesley", "committed_at": "2026-05-21T08:00:00Z"},
        ]
    }

    fake_cm = _make_fake_client(status, commits)

    import app.mcp_client.client as client_mod

    class FakeMCPToolClient:
        def __init__(self, *args, **kwargs):
            pass

        def session(self):
            return fake_cm

        async def call_tool(self, session, name, args):
            return await session.call_tool(session, name, args)

    monkeypatch.setattr(client_mod, "MCPToolClient", FakeMCPToolClient)
    import app.providers.github_mcp as gm_mod
    monkeypatch.setattr(gm_mod, "MCPToolClient", FakeMCPToolClient)

    context = await fetch_github_context(
        owner="wesleyzhangwq",
        repo="weatherflow",
        window_days=7,
        mcp_command="echo dummy",
    )

    assert isinstance(context, ProviderContext)
    assert context.source == "github"
    assert context.status == "success"
    assert context.window_days == 7
    assert "events" in context.signals
    assert "repos" in context.signals
    assert context.signals["repos_touched"] == 1
