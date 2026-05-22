"""GitHub MCP tool implementations."""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from mcp_servers.weatherflow_github.client import build_github_client

logger = logging.getLogger(__name__)

_WRITE_TOOLS_ENV = "WF_MCP_WRITE_TOOLS_ENABLED"


def _write_tools_enabled() -> bool:
    return os.environ.get(_WRITE_TOOLS_ENV, "false").lower() in ("true", "1", "yes")


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


async def get_repo_status(
    owner: str,
    repo: str,
    window_days: int = 7,
    *,
    _client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    async with (_client or build_github_client()) as client:
        repo_r = await client.get(f"/repos/{owner}/{repo}")
        repo_r.raise_for_status()
        repo_data = repo_r.json()

        commits_r = await client.get(
            f"/repos/{owner}/{repo}/commits",
            params={"per_page": 10},
        )
        commits_r.raise_for_status()
        commits = commits_r.json()

        issues_r = await client.get(
            f"/repos/{owner}/{repo}/issues",
            params={"state": "open", "per_page": 100},
        )
        issues_r.raise_for_status()
        all_issues = issues_r.json()

        prs_r = await client.get(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": "open", "per_page": 100},
        )
        prs_r.raise_for_status()
        open_prs = prs_r.json()

    real_issues = [i for i in all_issues if "pull_request" not in i]

    latest_commit = None
    if commits:
        c = commits[0]
        latest_commit = {
            "sha": c.get("sha", "")[:7],
            "message": (c.get("commit") or {}).get("message", "").split("\n")[0],
            "committed_at": (c.get("commit") or {}).get("committer", {}).get("date", ""),
        }

    recent_activity: list[dict[str, Any]] = []
    for c in commits[:5]:
        msg = (c.get("commit") or {}).get("message", "").split("\n")[0]
        at = (c.get("commit") or {}).get("committer", {}).get("date", "")
        recent_activity.append({"type": "commit", "title": msg, "at": at})

    return {
        "repo": f"{owner}/{repo}",
        "default_branch": repo_data.get("default_branch", "main"),
        "latest_commit": latest_commit,
        "open_issues_count": len(real_issues),
        "open_prs_count": len(open_prs),
        "recent_activity": recent_activity,
    }


async def get_recent_commits(
    owner: str,
    repo: str,
    branch: str = "main",
    since: Optional[str] = None,
    limit: int = 30,
    *,
    _client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"sha": branch, "per_page": min(limit, 100)}
    if since:
        params["since"] = since

    async with (_client or build_github_client()) as client:
        r = await client.get(f"/repos/{owner}/{repo}/commits", params=params)
        r.raise_for_status()
        raw = r.json()

    commits = []
    for c in raw[:limit]:
        commit_data = c.get("commit") or {}
        author = commit_data.get("author") or {}
        commits.append({
            "sha": c.get("sha", "")[:7],
            "message": commit_data.get("message", "").split("\n")[0],
            "author": author.get("name", ""),
            "committed_at": (commit_data.get("committer") or {}).get("date", ""),
        })

    return {"commits": commits}


async def list_issues(
    owner: str,
    repo: str,
    state: str = "open",
    labels: Optional[list[str]] = None,
    limit: int = 50,
    *,
    _client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "state": state,
        "per_page": min(limit, 100),
    }
    if labels:
        params["labels"] = ",".join(labels)

    async with (_client or build_github_client()) as client:
        r = await client.get(f"/repos/{owner}/{repo}/issues", params=params)
        r.raise_for_status()
        raw = r.json()

    issues = []
    for i in raw[:limit]:
        if "pull_request" in i:
            continue
        issues.append({
            "number": i.get("number"),
            "title": i.get("title", ""),
            "state": i.get("state", ""),
            "labels": [lb.get("name", "") for lb in (i.get("labels") or [])],
            "updated_at": i.get("updated_at", ""),
            "url": i.get("html_url", ""),
        })

    return {"issues": issues}


async def create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str = "",
    labels: Optional[list[str]] = None,
    dry_run: bool = False,
    *,
    _client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    if not _write_tools_enabled() and not dry_run:
        raise PermissionError("GitHub write tools are disabled.")

    if dry_run:
        return {
            "created": False,
            "dry_run": True,
            "issue": {"title": title, "body": body, "labels": labels or []},
        }

    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels

    async with (_client or build_github_client()) as client:
        r = await client.post(f"/repos/{owner}/{repo}/issues", json=payload)
        r.raise_for_status()
        data = r.json()

    return {
        "created": True,
        "issue": {
            "number": data.get("number"),
            "title": data.get("title", title),
            "url": data.get("html_url", ""),
        },
    }


async def get_file(
    owner: str,
    repo: str,
    path: str,
    ref: str = "main",
    max_bytes: int = 50000,
    *,
    _client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    async with (_client or build_github_client()) as client:
        r = await client.get(
            f"/repos/{owner}/{repo}/contents/{path.lstrip('/')}",
            params={"ref": ref},
        )
        r.raise_for_status()
        data = r.json()

    raw_content = base64.b64decode(data.get("content", "").replace("\n", "")).decode("utf-8", errors="replace")
    truncated = len(raw_content.encode("utf-8")) > max_bytes
    if truncated:
        raw_content = raw_content[:max_bytes]

    return {
        "path": path,
        "sha": data.get("sha", ""),
        "content": raw_content,
        "truncated": truncated,
    }


async def create_or_update_file(
    owner: str,
    repo: str,
    path: str,
    content: str,
    message: str,
    branch: str = "main",
    expected_sha: Optional[str] = None,
    dry_run: bool = False,
    *,
    _client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    if not _write_tools_enabled() and not dry_run:
        raise PermissionError("GitHub write tools are disabled.")

    if dry_run:
        return {
            "updated": False,
            "dry_run": True,
            "intended": {"path": path, "branch": branch, "message": message},
        }

    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    payload: dict[str, Any] = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }
    if expected_sha:
        payload["sha"] = expected_sha

    async with (_client or build_github_client()) as client:
        r = await client.put(
            f"/repos/{owner}/{repo}/contents/{path.lstrip('/')}",
            json=payload,
        )
        r.raise_for_status()
        data = r.json()

    commit = (data.get("commit") or {})
    return {
        "updated": True,
        "commit": {
            "sha": commit.get("sha", ""),
            "url": commit.get("html_url", ""),
        },
    }


__all__ = [
    "get_repo_status",
    "get_recent_commits",
    "list_issues",
    "create_issue",
    "get_file",
    "create_or_update_file",
]
