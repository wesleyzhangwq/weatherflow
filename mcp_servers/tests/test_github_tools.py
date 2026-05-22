from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_servers.weatherflow_github.tools import (
    create_issue,
    create_or_update_file,
    get_file,
    get_recent_commits,
    get_repo_status,
    list_issues,
)


def _make_client(*responses: dict[str, Any]) -> Any:
    """Fake async context manager client that returns responses in order."""
    mocks = []
    for data in responses:
        r = MagicMock()
        r.raise_for_status = MagicMock(return_value=None)
        r.json = MagicMock(return_value=data)
        mocks.append(r)

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    call_counter = {"n": 0}

    async def _get(*args: Any, **kwargs: Any) -> Any:
        idx = call_counter["n"]
        call_counter["n"] += 1
        if idx < len(mocks):
            return mocks[idx]
        return mocks[-1]

    async def _post(*args: Any, **kwargs: Any) -> Any:
        idx = call_counter["n"]
        call_counter["n"] += 1
        if idx < len(mocks):
            return mocks[idx]
        return mocks[-1]

    async def _put(*args: Any, **kwargs: Any) -> Any:
        idx = call_counter["n"]
        call_counter["n"] += 1
        if idx < len(mocks):
            return mocks[idx]
        return mocks[-1]

    client.get = _get
    client.post = _post
    client.put = _put
    return client


# ---------------------------------------------------------------------------
# get_repo_status
# ---------------------------------------------------------------------------


async def test_get_repo_status_returns_expected_shape() -> None:
    repo_resp = {"default_branch": "main", "full_name": "wesleyzhangwq/weatherflow"}
    commits_resp = [
        {
            "sha": "abc123def456",
            "commit": {
                "message": "Update provider docs",
                "author": {"name": "Wesley"},
                "committer": {"date": "2026-05-22T08:30:00Z"},
            },
        }
    ]
    issues_resp = [
        {"number": 4, "title": "Issue A", "state": "open"},
        {"number": 5, "title": "PR", "state": "open", "pull_request": {"url": "..."}},
    ]
    prs_resp = [{"number": 5, "title": "PR"}]

    client = _make_client(repo_resp, commits_resp, issues_resp, prs_resp)
    result = await get_repo_status("wesleyzhangwq", "weatherflow", _client=client)

    assert result["repo"] == "wesleyzhangwq/weatherflow"
    assert result["default_branch"] == "main"
    assert result["latest_commit"]["sha"] == "abc123d"
    assert result["open_issues_count"] == 1
    assert result["open_prs_count"] == 1
    assert len(result["recent_activity"]) >= 1


# ---------------------------------------------------------------------------
# get_recent_commits
# ---------------------------------------------------------------------------


async def test_get_recent_commits_returns_list() -> None:
    raw = [
        {
            "sha": "abc123def456",
            "commit": {
                "message": "Refine calendar setup",
                "author": {"name": "Wesley Zhang"},
                "committer": {"date": "2026-05-22T08:30:00Z"},
            },
        }
    ]
    client = _make_client(raw)
    result = await get_recent_commits("wesleyzhangwq", "weatherflow", _client=client)

    assert len(result["commits"]) == 1
    c = result["commits"][0]
    assert c["sha"] == "abc123d"
    assert c["message"] == "Refine calendar setup"
    assert c["author"] == "Wesley Zhang"


async def test_get_recent_commits_empty_list() -> None:
    client = _make_client([])
    result = await get_recent_commits("wesleyzhangwq", "weatherflow", _client=client)
    assert result["commits"] == []


# ---------------------------------------------------------------------------
# list_issues
# ---------------------------------------------------------------------------


async def test_list_issues_filters_out_prs() -> None:
    raw = [
        {"number": 12, "title": "Real issue", "state": "open", "labels": [], "updated_at": "2026-05-22T08:30:00Z", "html_url": "https://github.com/..."},
        {"number": 13, "title": "A PR", "state": "open", "labels": [], "updated_at": "2026-05-22T08:30:00Z", "html_url": "https://github.com/...", "pull_request": {"url": "..."}},
    ]
    client = _make_client(raw)
    result = await list_issues("wesleyzhangwq", "weatherflow", _client=client)

    assert len(result["issues"]) == 1
    assert result["issues"][0]["number"] == 12


async def test_list_issues_multi_commit_response() -> None:
    raw = [
        {"number": i, "title": f"Issue {i}", "state": "open", "labels": [], "updated_at": "", "html_url": ""}
        for i in range(3)
    ]
    client = _make_client(raw)
    result = await list_issues("wesleyzhangwq", "weatherflow", _client=client)
    assert len(result["issues"]) == 3


# ---------------------------------------------------------------------------
# create_issue
# ---------------------------------------------------------------------------


async def test_create_issue_dry_run(monkeypatch) -> None:
    monkeypatch.setenv("WF_MCP_WRITE_TOOLS_ENABLED", "false")
    client = _make_client({})
    result = await create_issue(
        "wesleyzhangwq", "weatherflow",
        title="Test issue",
        dry_run=True,
        _client=client,
    )
    assert result["dry_run"] is True
    assert result["created"] is False


async def test_create_issue_disabled_write_raises(monkeypatch) -> None:
    monkeypatch.setenv("WF_MCP_WRITE_TOOLS_ENABLED", "false")
    client = _make_client({})
    with pytest.raises(PermissionError, match="disabled"):
        await create_issue("wesleyzhangwq", "weatherflow", title="Test issue", _client=client)


async def test_create_issue_write_enabled_posts(monkeypatch) -> None:
    monkeypatch.setenv("WF_MCP_WRITE_TOOLS_ENABLED", "true")
    resp = {"number": 13, "title": "Test issue", "html_url": "https://github.com/..."}
    client = _make_client(resp)
    result = await create_issue(
        "wesleyzhangwq", "weatherflow",
        title="Test issue",
        dry_run=False,
        _client=client,
    )
    assert result["created"] is True
    assert result["issue"]["number"] == 13


# ---------------------------------------------------------------------------
# get_file
# ---------------------------------------------------------------------------


async def test_get_file_decodes_base64_content() -> None:
    raw_text = "# WeatherFlow\nHello"
    encoded = base64.b64encode(raw_text.encode()).decode()
    resp = {"sha": "blob-sha", "content": encoded}
    client = _make_client(resp)

    result = await get_file("wesleyzhangwq", "weatherflow", "README.md", _client=client)
    assert result["content"] == raw_text
    assert result["truncated"] is False
    assert result["sha"] == "blob-sha"


async def test_get_file_truncates_at_max_bytes() -> None:
    raw_text = "A" * 200
    encoded = base64.b64encode(raw_text.encode()).decode()
    resp = {"sha": "blob-sha", "content": encoded}
    client = _make_client(resp)

    result = await get_file("wesleyzhangwq", "weatherflow", "big.md", max_bytes=100, _client=client)
    assert result["truncated"] is True
    assert len(result["content"]) == 100


# ---------------------------------------------------------------------------
# create_or_update_file
# ---------------------------------------------------------------------------


async def test_create_or_update_file_dry_run(monkeypatch) -> None:
    monkeypatch.setenv("WF_MCP_WRITE_TOOLS_ENABLED", "false")
    client = _make_client({})
    result = await create_or_update_file(
        "wesleyzhangwq", "weatherflow",
        path="docs/log.md",
        content="# Log",
        message="docs: update log",
        dry_run=True,
        _client=client,
    )
    assert result["dry_run"] is True
    assert result["updated"] is False
    assert result["intended"]["path"] == "docs/log.md"


async def test_create_or_update_file_disabled_write_raises(monkeypatch) -> None:
    monkeypatch.setenv("WF_MCP_WRITE_TOOLS_ENABLED", "false")
    client = _make_client({})
    with pytest.raises(PermissionError):
        await create_or_update_file(
            "wesleyzhangwq", "weatherflow",
            path="docs/log.md", content="# Log", message="docs: update",
            _client=client,
        )


async def test_create_or_update_file_write_enabled_puts(monkeypatch) -> None:
    monkeypatch.setenv("WF_MCP_WRITE_TOOLS_ENABLED", "true")
    resp = {"content": {}, "commit": {"sha": "commit-sha", "html_url": "https://github.com/..."}}
    client = _make_client(resp)
    result = await create_or_update_file(
        "wesleyzhangwq", "weatherflow",
        path="docs/log.md", content="# Log", message="docs: update",
        expected_sha="existing-blob-sha",
        dry_run=False,
        _client=client,
    )
    assert result["updated"] is True
    assert result["commit"]["sha"] == "commit-sha"


async def test_create_or_update_file_missing_expected_sha_still_creates(monkeypatch) -> None:
    monkeypatch.setenv("WF_MCP_WRITE_TOOLS_ENABLED", "true")
    resp = {"content": {}, "commit": {"sha": "new-sha", "html_url": ""}}
    client = _make_client(resp)
    result = await create_or_update_file(
        "wesleyzhangwq", "weatherflow",
        path="docs/new.md", content="New file", message="docs: create",
        expected_sha=None,
        dry_run=False,
        _client=client,
    )
    assert result["updated"] is True
