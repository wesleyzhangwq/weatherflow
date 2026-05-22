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
    """Backward-compatible single-repo wrapper."""
    return await fetch_github_context_multi_repo(
        repos=[(owner, repo)],
        window_days=window_days,
        mcp_command=mcp_command,
        timeout=timeout,
    )


async def fetch_github_context_multi_repo(
    *,
    repos: list[tuple[str, str]],
    window_days: int = 7,
    mcp_command: str,
    timeout: float = 20.0,
) -> ProviderContext:
    """Fetch and aggregate GitHub context from multiple repos.

    Args:
        repos: List of (owner, repo) tuples to monitor.
        window_days: Time window for activity.
        mcp_command: MCP server command to launch.
        timeout: Tool call timeout in seconds.
    """
    client = MCPToolClient(mcp_command, timeout=timeout)

    # Initialize aggregate signals
    all_events: dict[str, Any] = {}
    all_repos: list[str] = []
    total_event_count = 0
    event_type_counts: dict[str, int] = {}
    all_coverage: dict[str, Any] = {}
    failed_repos: list[str] = []

    async with client.session() as session:
        for owner, repo in repos:
            repo_full = f"{owner}/{repo}"
            try:
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

                # Process this repo's results
                _aggregate_repo_result(
                    owner,
                    repo,
                    status,
                    commits,
                    all_repos,
                    event_type_counts,
                    all_coverage,
                )

            except Exception as e:
                logger.warning(f"Failed to fetch GitHub context for {repo_full}: {e}")
                failed_repos.append(repo_full)

    # Calculate total events from event types
    total_event_count = sum(event_type_counts.values())

    warnings = []
    if not all_repos:
        warnings.append("No GitHub repos were successfully queried.")
    if failed_repos:
        warnings.append(f"Failed to fetch data for: {', '.join(failed_repos)}")
    if total_event_count == 0:
        warnings.append("No recent GitHub events returned for this window.")

    return ProviderContext(
        source="github",
        status="success",
        window_days=window_days,
        signals={
            "events": total_event_count,
            "event_types": event_type_counts,
            "repos_touched": len(all_repos),
            "repos": all_repos,
        },
        coverage=all_coverage,
        warnings=warnings,
    )


def _aggregate_repo_result(
    owner: str,
    repo: str,
    status: dict[str, Any],
    commits: dict[str, Any],
    all_repos: list[str],
    event_type_counts: dict[str, int],
    all_coverage: dict[str, Any],
) -> None:
    """Aggregate a single repo's results into the overall context.

    Updates all_repos, event_type_counts, and all_coverage in-place.
    """
    repo_full = status.get("repo", f"{owner}/{repo}")
    all_repos.append(repo_full)

    commit_list = commits.get("commits", [])
    activity = status.get("recent_activity", [])

    commit_count = len(commit_list)
    issue_count = int(status.get("open_issues_count", 0))
    pr_count = int(status.get("open_prs_count", 0))

    # Accumulate event type counts
    if commit_count > 0:
        event_type_counts["Commit"] = event_type_counts.get("Commit", 0) + commit_count
    if issue_count > 0:
        event_type_counts["Issue"] = event_type_counts.get("Issue", 0) + issue_count
    if pr_count > 0:
        event_type_counts["PullRequest"] = event_type_counts.get("PullRequest", 0) + pr_count

    # Store per-repo coverage details
    all_coverage[repo_full] = {
        "commit_count": commit_count,
        "open_issues_count": issue_count,
        "open_prs_count": pr_count,
    }


__all__ = ["fetch_github_context", "fetch_github_context_multi_repo"]
