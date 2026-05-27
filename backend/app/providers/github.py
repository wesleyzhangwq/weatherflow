"""GitHub MCP provider — raw activity snapshot fetcher for T2."""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings, get_settings
from app.mcp_client import MCPToolClient
from app.memory.schemas import GithubSnapshotPayload

logger = logging.getLogger(__name__)


async def fetch_snapshot(
    *,
    settings: Settings | None = None,
    window_days: int = 7,
) -> GithubSnapshotPayload:
    s = settings or get_settings()
    repos = s.parsed_monitored_repos
    if not repos:
        return GithubSnapshotPayload(window_days=window_days)

    all_commits: list[dict[str, Any]] = []
    all_prs: list[dict[str, Any]] = []
    all_issues: list[dict[str, Any]] = []
    active_repos: list[str] = []

    client = MCPToolClient(s.wf_github_mcp_command, timeout=s.wf_mcp_tool_timeout_seconds)
    async with client.session() as session:
        for owner, repo in repos:
            repo_full = f"{owner}/{repo}"
            try:
                # Default branch varies (main/master/etc) — fetch first so
                # get_recent_commits doesn't 404 on a wrong assumption.
                status = await client.call_tool(
                    session,
                    "github.get_repo_status",
                    {"owner": owner, "repo": repo, "window_days": window_days},
                )
                branch = status.get("default_branch") or "main"

                commits = await client.call_tool(
                    session,
                    "github.get_recent_commits",
                    {"owner": owner, "repo": repo, "branch": branch, "limit": 50},
                )
                for c in commits.get("commits", []):
                    if isinstance(c, dict):
                        c = {**c, "repo": repo_full}
                        all_commits.append(c)

                prs = await client.call_tool(
                    session,
                    "github.list_pull_requests",
                    {"owner": owner, "repo": repo, "state": "open", "limit": 30},
                )
                for p in prs.get("pull_requests", prs.get("prs", [])):
                    if isinstance(p, dict):
                        p = {**p, "repo": repo_full}
                        all_prs.append(p)

                issues = await client.call_tool(
                    session,
                    "github.list_issues",
                    {"owner": owner, "repo": repo, "state": "open", "limit": 30},
                )
                for i in issues.get("issues", []):
                    if isinstance(i, dict):
                        i = {**i, "repo": repo_full}
                        all_issues.append(i)

                repo_commits = commits.get("commits") or []
                repo_prs = prs.get("pull_requests") or prs.get("prs") or []
                repo_issues = issues.get("issues") or []
                if repo_commits or repo_prs or repo_issues:
                    active_repos.append(repo_full)

            except Exception as exc:
                logger.warning("GitHub snapshot fetch failed for %s: %s", repo_full, exc)

    return GithubSnapshotPayload(
        commits=all_commits,
        prs=all_prs,
        issues=all_issues,
        active_repos=active_repos,
        window_days=window_days,
    )


__all__ = ["fetch_snapshot"]
