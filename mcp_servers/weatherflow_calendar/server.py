"""WeatherFlow Calendar MCP server."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_servers.weatherflow_calendar.tools import (
    create_event,
    create_focus_block,
    delete_event,
    find_free_slots,
    search_events,
    update_event,
)

mcp = FastMCP("WeatherFlow Calendar")


@mcp.tool(name="calendar.search_events")
async def tool_search_events(
    start_time: str,
    end_time: str,
    keyword: str = "",
    calendar_id: str = "primary",
    max_results: int = 50,
) -> dict:
    """Search calendar events in a time window."""
    return await search_events(
        start_time=start_time,
        end_time=end_time,
        keyword=keyword or None,
        calendar_id=calendar_id,
        max_results=max_results,
    )


@mcp.tool(name="calendar.find_free_slots")
async def tool_find_free_slots(
    start_time: str,
    end_time: str,
    min_duration_minutes: int = 45,
    calendar_id: str = "primary",
    workday_start: str = "09:00",
    workday_end: str = "18:00",
) -> dict:
    """Find free time slots in a window, respecting existing events."""
    return await find_free_slots(
        start_time=start_time,
        end_time=end_time,
        min_duration_minutes=min_duration_minutes,
        calendar_id=calendar_id,
        workday_start=workday_start,
        workday_end=workday_end,
    )


@mcp.tool(name="calendar.create_event")
async def tool_create_event(
    title: str,
    start_time: str,
    end_time: str,
    calendar_id: str = "primary",
    description: str = "Created by WeatherFlow",
    dry_run: bool = False,
) -> dict:
    """Create a calendar event. Requires WF_MCP_WRITE_TOOLS_ENABLED=true or dry_run=true."""
    return await create_event(
        title=title,
        start_time=start_time,
        end_time=end_time,
        calendar_id=calendar_id,
        description=description,
        dry_run=dry_run,
    )


@mcp.tool(name="calendar.create_focus_block")
async def tool_create_focus_block(
    title: str,
    duration_minutes: int,
    date: str,
    preferred_time: str = "morning",
    priority: str = "high",
    calendar_id: str = "primary",
    dry_run: bool = False,
) -> dict:
    """Create a focus block on a given date. Finds a suitable free slot automatically."""
    return await create_focus_block(
        title=title,
        duration_minutes=duration_minutes,
        date=date,
        preferred_time=preferred_time,
        priority=priority,
        calendar_id=calendar_id,
        dry_run=dry_run,
    )


@mcp.tool(name="calendar.update_event")
async def tool_update_event(
    event_id: str,
    calendar_id: str = "primary",
    title: str = "",
    start_time: str = "",
    end_time: str = "",
    description: str = "",
    dry_run: bool = False,
) -> dict:
    """Update an existing calendar event. Requires WF_MCP_WRITE_TOOLS_ENABLED=true."""
    return await update_event(
        event_id=event_id,
        calendar_id=calendar_id,
        title=title or None,
        start_time=start_time or None,
        end_time=end_time or None,
        description=description or None,
        dry_run=dry_run,
    )


@mcp.tool(name="calendar.delete_event")
async def tool_delete_event(
    event_id: str,
    calendar_id: str = "primary",
    dry_run: bool = False,
) -> dict:
    """Delete a calendar event. Requires WF_MCP_WRITE_TOOLS_ENABLED=true."""
    return await delete_event(event_id=event_id, calendar_id=calendar_id, dry_run=dry_run)


if __name__ == "__main__":
    mcp.run()
