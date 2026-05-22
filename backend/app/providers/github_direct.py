"""GitHub direct connector for developer rhythm evidence.

Deprecated: direct provider calls will be removed after MCP mode has been stable
for one full release. Prefer DEV_REVIEW_PROVIDER_MODE=mcp going forward.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.memory.schemas import ProviderContext
from app.mcp.base import MCPConnector

logger = logging.getLogger(__name__)


class GithubConnector(MCPConnector):
    name = "github"

    def __init__(self, token: str, base_url: str = "https://api.github.com") -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")

    async def health(self) -> dict[str, Any]:
        async with self._client() as client:
            r = await client.get("/user")
            ok = r.status_code == 200
        return {
            "name": self.name,
            "status": "ok" if ok else "auth_failed",
            "code": r.status_code,
        }

    async def fetch(self, *, days: int = 7, **_: Any) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with self._client() as client:
            user_response = await client.get("/user")
            user_response.raise_for_status()
            user = user_response.json()
            login = user.get("login")
            if not login:
                raise ValueError("GitHub /user response did not include login.")

            r = await client.get(f"/users/{login}/events", params={"per_page": 100})
            r.raise_for_status()
            events = r.json()

        recent = [
            e for e in events
            if _parse_dt(e.get("created_at")) and _parse_dt(e["created_at"]) >= cutoff
        ]
        by_type: dict[str, int] = {}
        repos: set[str] = set()
        for e in recent:
            by_type[e.get("type", "Unknown")] = by_type.get(e.get("type", "Unknown"), 0) + 1
            repo = (e.get("repo") or {}).get("name")
            if repo:
                repos.add(repo)

        return {
            "login": login,
            "window_days": days,
            "events": len(recent),
            "by_type": by_type,
            "repos_touched": len(repos),
            "repo_list": sorted(repos),
        }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=httpx.Timeout(20.0, connect=10.0),
        )


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_github_summary(summary: dict[str, Any], *, window_days: int) -> ProviderContext:
    events = int(summary.get("events") or 0)
    login = summary.get("login")
    repos = list(summary.get("repo_list") or [])
    warnings = []
    if events == 0:
        warnings.append("No recent GitHub events returned for this window.")

    return ProviderContext(
        source="github",
        status="success",
        window_days=window_days,
        signals={
            "login": login,
            "events": events,
            "event_types": dict(summary.get("by_type") or {}),
            "repos_touched": int(summary.get("repos_touched") or len(repos)),
            "repos": repos,
        },
        coverage={
            "login": login,
            "raw_event_count": events,
        },
        warnings=warnings,
    )


__all__ = ["GithubConnector", "normalize_github_summary"]
