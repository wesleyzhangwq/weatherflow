"""Tests for provider mode settings in config."""

from __future__ import annotations

import pytest

from app.config import Settings, get_settings


def test_default_provider_mode_is_direct() -> None:
    s = Settings()
    assert s.dev_review_provider_mode == "direct"


def test_provider_mode_reads_from_env(monkeypatch) -> None:
    monkeypatch.setenv("DEV_REVIEW_PROVIDER_MODE", "mcp")
    get_settings.cache_clear()
    s = get_settings()
    assert s.dev_review_provider_mode == "mcp"
    get_settings.cache_clear()


def test_wf_mcp_write_tools_disabled_by_default() -> None:
    s = Settings()
    assert s.wf_mcp_write_tools_enabled is False


def test_wf_mcp_write_tools_enabled_via_env(monkeypatch) -> None:
    monkeypatch.setenv("WF_MCP_WRITE_TOOLS_ENABLED", "true")
    get_settings.cache_clear()
    s = get_settings()
    assert s.wf_mcp_write_tools_enabled is True
    get_settings.cache_clear()


def test_mcp_tool_timeout_defaults_to_20() -> None:
    s = Settings()
    assert s.wf_mcp_tool_timeout_seconds == 20.0


def test_github_mcp_command_has_sensible_default() -> None:
    s = Settings()
    assert "weatherflow_github" in s.wf_github_mcp_command


def test_calendar_mcp_command_has_sensible_default() -> None:
    s = Settings()
    assert "weatherflow_calendar" in s.wf_calendar_mcp_command
