"""WeatherFlow GitHub MCP server."""

from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from mcp_servers.weatherflow_github.tools import (
    create_issue,
    create_or_update_file,
    get_file,
    get_recent_commits,
    get_repo_status,
    list_issues,
)

mcp = FastMCP("WeatherFlow GitHub")


@mcp.tool(name="github.get_repo_status")
async def tool_get_repo_status(owner: str, repo: str, window_days: int = 7) -> dict:
    """Get repository status: default branch, latest commit, open issues and PRs."""
    return await get_repo_status(owner=owner, repo=repo, window_days=window_days)


@mcp.tool(name="github.get_recent_commits")
async def tool_get_recent_commits(
    owner: str,
    repo: str,
    branch: str = "main",
    since: str = "",
    limit: int = 30,
) -> dict:
    """Get recent commits for a repository branch."""
    return await get_recent_commits(
        owner=owner,
        repo=repo,
        branch=branch,
        since=since or None,
        limit=limit,
    )


@mcp.tool(name="github.list_issues")
async def tool_list_issues(
    owner: str,
    repo: str,
    state: str = "open",
    labels: str = "",
    limit: int = 50,
) -> dict:
    """List issues for a repository. Pass labels as comma-separated string."""
    label_list = [lb.strip() for lb in labels.split(",") if lb.strip()] if labels else None
    return await list_issues(owner=owner, repo=repo, state=state, labels=label_list, limit=limit)


@mcp.tool(name="github.create_issue")
async def tool_create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str = "",
    labels: str = "",
    dry_run: bool = False,
) -> dict:
    """Create a GitHub issue. Requires WF_MCP_WRITE_TOOLS_ENABLED=true or dry_run=true."""
    label_list = [lb.strip() for lb in labels.split(",") if lb.strip()] if labels else None
    return await create_issue(
        owner=owner, repo=repo, title=title, body=body, labels=label_list, dry_run=dry_run
    )


@mcp.tool(name="github.get_file")
async def tool_get_file(
    owner: str,
    repo: str,
    path: str,
    ref: str = "main",
    max_bytes: int = 50000,
) -> dict:
    """Get a file from a GitHub repository, decoded from base64."""
    return await get_file(owner=owner, repo=repo, path=path, ref=ref, max_bytes=max_bytes)


@mcp.tool(name="github.create_or_update_file")
async def tool_create_or_update_file(
    owner: str,
    repo: str,
    path: str,
    content: str,
    message: str,
    branch: str = "main",
    expected_sha: str = "",
    dry_run: bool = False,
) -> dict:
    """Create or update a file in a GitHub repository. Requires WF_MCP_WRITE_TOOLS_ENABLED=true."""
    return await create_or_update_file(
        owner=owner,
        repo=repo,
        path=path,
        content=content,
        message=message,
        branch=branch,
        expected_sha=expected_sha or None,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    mcp.run()
