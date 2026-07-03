"""WeatherFlow GitHub MCP server."""

from __future__ import annotations


from mcp.server.fastmcp import FastMCP

from mcp_servers.weatherflow_github.tools import (
    create_issue,
    create_or_update_file,
    get_file,
    get_recent_commits,
    get_repo_status,
    list_issues,
    list_pull_requests,
    list_repos,
    update_issue,
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


@mcp.tool(name="github.list_repos")
async def tool_list_repos(
    visibility: str = "all",
    affiliation: str = "owner,collaborator,organization_member",
    limit: int = 50,
) -> dict:
    """List repositories accessible to the authenticated user."""
    return await list_repos(visibility=visibility, affiliation=affiliation, limit=limit)


@mcp.tool(name="github.update_issue")
async def tool_update_issue(
    owner: str,
    repo: str,
    issue_number: int,
    title: str = "",
    body: str = "",
    state: str = "",
    labels: str = "",
    dry_run: bool = False,
) -> dict:
    """Update a GitHub issue. Requires WF_MCP_WRITE_TOOLS_ENABLED=true."""
    label_list = [lb.strip() for lb in labels.split(",") if lb.strip()] if labels else None
    return await update_issue(
        owner=owner,
        repo=repo,
        issue_number=issue_number,
        title=title or None,
        body=body or None,
        state=state or None,
        labels=label_list,
        dry_run=dry_run,
    )


@mcp.tool(name="github.list_pull_requests")
async def tool_list_pull_requests(
    owner: str,
    repo: str,
    state: str = "open",
    limit: int = 30,
) -> dict:
    """List pull requests for a repository."""
    return await list_pull_requests(owner=owner, repo=repo, state=state, limit=limit)


if __name__ == "__main__":
    mcp.run()
