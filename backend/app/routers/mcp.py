"""MCP connector endpoints."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.mcp.github import GithubConnector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mcp", tags=["mcp"])

Provider = Literal["github", "google_calendar"]


@router.get("/providers")
async def list_providers() -> list[dict[str, str]]:
    settings = get_settings()
    return [
        {
            "name": "github",
            "status": "ready" if settings.github_token else "needs_config",
            "hint": "set GITHUB_TOKEN to enable",
        },
        {
            "name": "google_calendar",
            "status": (
                "ready"
                if settings.google_calendar_access_token or settings.google_calendar_token_file
                else "needs_config"
            ),
            "hint": "run wf setup-calendar or set GOOGLE_CALENDAR_ACCESS_TOKEN",
        },
    ]


@router.post("/github/sync")
async def github_sync(days: int = 7) -> dict[str, Any]:
    settings = get_settings()
    if not settings.github_token:
        raise HTTPException(status_code=400, detail="GITHUB_TOKEN is not set.")
    conn = GithubConnector(token=settings.github_token)
    try:
        summary = await conn.fetch(days=days)
    except Exception as exc:
        logger.exception("github sync failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return summary


@router.post("/{provider}")
async def call_provider_default(provider: Provider) -> dict:
    """Generic stub for unimplemented providers."""
    if provider == "github":
        raise HTTPException(
            status_code=400,
            detail="Use /api/mcp/github/sync for GitHub.",
        )
    if provider == "google_calendar":
        raise HTTPException(
            status_code=400,
            detail="Use /api/dev-review/runs to fetch Google Calendar evidence.",
        )
    raise HTTPException(
        status_code=501,
        detail=f"MCP connector '{provider}' is reserved for a future iteration.",
    )
