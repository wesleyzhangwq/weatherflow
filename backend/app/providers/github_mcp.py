"""GitHub MCP provider wrapper — calls GitHub MCP tools and returns ProviderContext."""

from __future__ import annotations

import logging
from typing import Any

from app.memory.schemas import ProviderContext
from app.mcp_client.client import MCPToolClient

logger = logging.getLogger(__name__)


async def fetch_github_context(
    *,
    owner: str,
    repo: str,
    window_days: int = 7,
    mcp_command: str,
    timeout: float = 20.0,
) -> ProviderContext:
    client = MCPToolClient(mcp_command, timeout=timeout)
    async with client.session() as session:
        status = await client.call_tool(
            session,
            "github.get_repo_status",
            {"owner": owner, "repo": repo, "window_days": window_days},
        )
        commits = await client.call_tool(
            session,
            "github.get_recent_commits",
            {"owner": owner, "repo": repo, "limit": 30},
        )

    commit_list = commits.get("commits", [])
    activity = status.get("recent_activity", [])

    commit_count = len(commit_list)
    issue_count = int(status.get("open_issues_count", 0))
    pr_count = int(status.get("open_prs_count", 0))
    repo_full = status.get("repo", f"{owner}/{repo}")

    event_types: dict[str, int] = {}
    if commit_count:
        event_types["Commit"] = commit_count
    if issue_count:
        event_types["Issue"] = issue_count
    if pr_count:
        event_types["PullRequest"] = pr_count

    total_events = commit_count + len(activity)

    warnings = []
    if total_events == 0:
        warnings.append("No recent GitHub events returned for this window.")

    return ProviderContext(
        source="github",
        status="success",
        window_days=window_days,
        signals={
            "events": total_events,
            "event_types": event_types,
            "repos_touched": 1,
            "repos": [repo_full],
        },
        coverage={
            "repo": repo_full,
            "commit_count": commit_count,
            "open_issues_count": issue_count,
            "open_prs_count": pr_count,
        },
        warnings=warnings,
    )


__all__ = ["fetch_github_context"]
