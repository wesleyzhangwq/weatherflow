from __future__ import annotations

from mcp_servers.weatherflow_calendar.server import mcp


def test_calendar_server_registers_four_mvp_tools() -> None:
    tools = mcp._tool_manager.list_tools()
    names = {t.name for t in tools}
    expected = {
        "calendar.search_events",
        "calendar.find_free_slots",
        "calendar.create_event",
        "calendar.create_focus_block",
    }
    assert expected.issubset(names), f"Missing tools: {expected - names}"


def test_calendar_server_name() -> None:
    assert mcp.name == "WeatherFlow Calendar"
