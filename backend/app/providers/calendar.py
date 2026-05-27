"""Calendar MCP provider — raw snapshot fetcher for T2 scheduled checks.

Returns a CalendarSnapshotPayload-compatible dict. The structured payload is
stored verbatim in L1 so future evidence references can be drilled down to
the original event list (ADR D14).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import Settings, get_settings
from app.mcp_client import MCPToolClient
from app.memory.schemas import CalendarSnapshotPayload

logger = logging.getLogger(__name__)


async def fetch_snapshot(
    *,
    settings: Settings | None = None,
    window_days: int = 3,
) -> CalendarSnapshotPayload:
    s = settings or get_settings()
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=window_days)).isoformat()
    end = (now + timedelta(days=window_days)).isoformat()

    client = MCPToolClient(s.wf_calendar_mcp_command, timeout=s.wf_mcp_tool_timeout_seconds)
    async with client.session() as session:
        result = await client.call_tool(
            session,
            "calendar.search_events",
            {
                "start_time": start,
                "end_time": end,
                "calendar_id": s.google_calendar_calendar_id,
                "max_results": 200,
            },
        )

    events = _normalize_events(result.get("events", []))
    return CalendarSnapshotPayload(
        events=events,
        window_start=start,
        window_end=end,
        calendar_id=s.google_calendar_calendar_id,
    )


def _normalize_events(events: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in events:
        if not isinstance(e, dict):
            continue
        out.append(
            {
                "id": e.get("id"),
                "summary": e.get("summary") or e.get("title") or "",
                "start": e.get("start") or e.get("start_time"),
                "end": e.get("end") or e.get("end_time"),
                "duration_minutes": e.get("duration_minutes", 0),
                "attendees_count": e.get("attendees_count", 0),
            }
        )
    return out


__all__ = ["fetch_snapshot"]
