"""Calendar MCP provider wrapper — calls Calendar MCP tools and returns ProviderContext."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.memory.schemas import ProviderContext
from app.mcp_client.client import MCPToolClient

logger = logging.getLogger(__name__)


async def fetch_calendar_context(
    *,
    calendar_id: str = "primary",
    window_days: int = 7,
    mcp_command: str,
    timeout: float = 20.0,
) -> ProviderContext:
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=window_days)).isoformat()
    time_max = now.isoformat()

    client = MCPToolClient(mcp_command, timeout=timeout)
    async with client.session() as session:
        result = await client.call_tool(
            session,
            "calendar.search_events",
            {
                "start_time": time_min,
                "end_time": time_max,
                "calendar_id": calendar_id,
                "max_results": 100,
            },
        )

    events = result.get("events", [])
    coverage = result.get("coverage", {})

    meeting_minutes = 0
    after_hours_events = 0
    for ev in events:
        meeting_minutes += int(ev.get("duration_minutes", 0))
        start_value = str(ev.get("start", ""))
        if "T" in start_value:
            try:
                start_dt = datetime.fromisoformat(start_value.replace("Z", "+00:00"))
                if start_dt.hour < 9 or start_dt.hour >= 17:
                    after_hours_events += 1
            except ValueError:
                pass

    return ProviderContext(
        source="google_calendar",
        status="success",
        window_days=window_days,
        signals={
            "meeting_count": len(events),
            "meeting_hours": round(meeting_minutes / 60, 2),
            "after_hours_events": after_hours_events,
            "events": events,
        },
        coverage={
            "calendar_id": coverage.get("calendar_id", calendar_id),
            "event_count": coverage.get("event_count", len(events)),
        },
        warnings=[],
    )


__all__ = ["fetch_calendar_context"]
