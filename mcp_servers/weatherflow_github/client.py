"""GitHub HTTP client helper for MCP server tools."""

from __future__ import annotations

import os

import httpx


def build_github_client(
    base_url: str = "https://api.github.com",
) -> httpx.AsyncClient:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN environment variable is not set. "
            "Export a personal access token to use GitHub MCP tools."
        )
    return httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=httpx.Timeout(20.0, connect=10.0),
    )


__all__ = ["build_github_client"]
