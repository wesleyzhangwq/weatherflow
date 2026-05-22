"""Provider registry — chooses direct or MCP provider based on settings."""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings
from app.memory.schemas import ProviderContext

logger = logging.getLogger(__name__)


async def get_github_context(
    settings: Settings,
    *,
    window_days: int = 7,
) -> ProviderContext:
    mode = settings.dev_review_provider_mode

    if mode == "direct":
        return await _github_direct(settings, window_days=window_days)
    if mode == "mcp":
        return await _github_mcp(settings, window_days=window_days)
    if mode == "dual":
        return await _github_dual(settings, window_days=window_days)

    logger.warning("Unknown provider mode '%s', falling back to direct.", mode)
    return await _github_direct(settings, window_days=window_days)


async def get_calendar_context(
    settings: Settings,
    *,
    window_days: int = 7,
    calendar_token_file: str = "",
) -> ProviderContext:
    mode = settings.dev_review_provider_mode

    if mode == "direct":
        return await _calendar_direct(settings, window_days=window_days, calendar_token_file=calendar_token_file)
    if mode == "mcp":
        return await _calendar_mcp(settings, window_days=window_days)
    if mode == "dual":
        return await _calendar_dual(settings, window_days=window_days, calendar_token_file=calendar_token_file)

    logger.warning("Unknown provider mode '%s', falling back to direct.", mode)
    return await _calendar_direct(settings, window_days=window_days, calendar_token_file=calendar_token_file)


async def _github_direct(settings: Settings, *, window_days: int) -> ProviderContext:
    from app.providers.github_direct import GithubConnector, normalize_github_summary
    summary = await GithubConnector(settings.github_token).fetch(days=window_days)
    return normalize_github_summary(summary, window_days=window_days)


async def _github_mcp(settings: Settings, *, window_days: int) -> ProviderContext:
    from app.providers.github_mcp import fetch_github_context_multi_repo
    repos = settings.parsed_monitored_repos
    return await fetch_github_context_multi_repo(
        repos=repos,
        window_days=window_days,
        mcp_command=settings.wf_github_mcp_command,
        timeout=settings.wf_mcp_tool_timeout_seconds,
    )


async def _github_dual(settings: Settings, *, window_days: int) -> ProviderContext:
    direct = await _github_direct(settings, window_days=window_days)
    try:
        mcp = await _github_mcp(settings, window_days=window_days)
        _log_github_comparison(direct, mcp)
    except Exception:
        logger.exception("GitHub MCP provider failed in dual mode; returning direct result.")
    return direct


async def _calendar_direct(
    settings: Settings, *, window_days: int, calendar_token_file: str
) -> ProviderContext:
    from app.providers.google_calendar_direct import GoogleCalendarConnector
    return await GoogleCalendarConnector(
        access_token=settings.google_calendar_access_token,
        token_file=calendar_token_file,
        calendar_id=settings.google_calendar_calendar_id,
        base_url=settings.google_calendar_base_url,
    ).fetch(days=window_days)


async def _calendar_mcp(settings: Settings, *, window_days: int) -> ProviderContext:
    from app.providers.google_calendar_mcp import fetch_calendar_context
    return await fetch_calendar_context(
        calendar_id=settings.google_calendar_calendar_id,
        window_days=window_days,
        mcp_command=settings.wf_calendar_mcp_command,
        timeout=settings.wf_mcp_tool_timeout_seconds,
    )


async def _calendar_dual(
    settings: Settings, *, window_days: int, calendar_token_file: str
) -> ProviderContext:
    direct = await _calendar_direct(settings, window_days=window_days, calendar_token_file=calendar_token_file)
    try:
        mcp = await _calendar_mcp(settings, window_days=window_days)
        _log_calendar_comparison(direct, mcp)
    except Exception:
        logger.exception("Calendar MCP provider failed in dual mode; returning direct result.")
    return direct


def _log_github_comparison(direct: ProviderContext, mcp: ProviderContext) -> None:
    d_events = direct.signals.get("events", 0)
    m_events = mcp.signals.get("events", 0)
    d_repos = set(direct.signals.get("repos", []))
    m_repos = set(mcp.signals.get("repos", []))
    if abs(d_events - m_events) > max(5, d_events * 0.3):
        logger.warning("GitHub dual mode: event count mismatch direct=%d mcp=%d", d_events, m_events)
    if d_repos != m_repos:
        logger.warning("GitHub dual mode: repo mismatch direct=%s mcp=%s", d_repos, m_repos)


def _log_calendar_comparison(direct: ProviderContext, mcp: ProviderContext) -> None:
    d_count = direct.signals.get("meeting_count", 0)
    m_count = mcp.signals.get("meeting_count", 0)
    d_hours = direct.signals.get("meeting_hours", 0)
    m_hours = mcp.signals.get("meeting_hours", 0)
    if d_count != m_count:
        logger.warning("Calendar dual mode: meeting count mismatch direct=%d mcp=%d", d_count, m_count)
    if abs(float(d_hours) - float(m_hours)) > 0.5:
        logger.warning("Calendar dual mode: meeting hours mismatch direct=%.1f mcp=%.1f", d_hours, m_hours)


__all__ = ["get_github_context", "get_calendar_context"]
