"""MCP connector endpoints (minimal).

GitHub — recent activity for the authenticated token.
Notes — server-side vault scan → same aggregate row as ``/api/sensors/notes``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.mcp.github import GithubConnector
from app.mcp.notes_ingest import scan_markdown_root
from app.memory import notes_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mcp", tags=["mcp"])

Provider = Literal["github", "notes"]


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
            "name": "notes",
            "status": "ready",
            "hint": "POST /api/mcp/notes/sync with vault root path",
        },
    ]


@router.post("/notes/sync")
async def notes_sync(root: str, window_days: int = 14) -> dict[str, Any]:
    """Scan a markdown / Obsidian directory server-side; store aggregate only."""
    path = Path(root).expanduser()
    if not path.is_dir():
        raise HTTPException(status_code=404, detail=f"Not a directory: {path}")
    try:
        payload = scan_markdown_root(path, window_days=window_days)
    except Exception as exc:
        logger.exception("notes sync failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    rid = notes_repo.add(payload)
    return {"id": rid, "ingested": payload.model_dump()}


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
    if provider in {"github", "notes"}:
        raise HTTPException(
            status_code=400,
            detail=f"Use /api/mcp/{provider}/sync for {provider}.",
        )
    raise HTTPException(
        status_code=501,
        detail=f"MCP connector '{provider}' is reserved for a future iteration.",
    )
