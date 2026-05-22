from __future__ import annotations

from mcp_servers.weatherflow_github.server import mcp


def test_github_server_registers_mvp_tools() -> None:
    tools = mcp._tool_manager.list_tools()
    names = {t.name for t in tools}
    expected = {
        "github.get_repo_status",
        "github.get_recent_commits",
        "github.list_issues",
        "github.create_issue",
        "github.get_file",
        "github.create_or_update_file",
    }
    assert expected.issubset(names), f"Missing tools: {expected - names}"


def test_github_server_name() -> None:
    assert mcp.name == "WeatherFlow GitHub"
