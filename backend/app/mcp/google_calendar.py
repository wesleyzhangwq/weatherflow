"""Google Calendar MCP connector for normalized dev review signals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.memory.schemas import ProviderContext
from app.mcp.base import MCPConnector

DEFAULT_BASE_URL = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarConnector(MCPConnector):
    name = "google_calendar"

    def __init__(
        self,
        access_token: str,
        calendar_id: str = "primary",
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self.access_token = access_token
        self.calendar_id = calendar_id
        self.base_url = base_url.rstrip("/")

    async def health(self) -> dict[str, Any]:
        async with self._client() as client:
            r = await client.get(f"/calendars/{_calendar_path(self.calendar_id)}")
            ok = r.status_code == 200
            data = r.json() if ok else {}
        return {
            "name": self.name,
            "status": "ok" if ok else "auth_failed",
            "code": r.status_code,
            "calendar_id": self.calendar_id,
            "calendar_name": data.get("summary", "") if ok else "",
        }

    async def fetch(self, *, days: int = 7, **_: Any) -> ProviderContext:
        now = datetime.now(timezone.utc)
        time_min = now - timedelta(days=days)
        time_max = now
        async with self._client() as client:
            r = await client.get(
                f"/calendars/{_calendar_path(self.calendar_id)}/events",
                params={
                    "timeMin": time_min.isoformat(),
                    "timeMax": time_max.isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": 100,
                },
            )
            r.raise_for_status()
            data = r.json()

        events = sanitize_calendar_events(data.get("items") or [])
        after_hours_events = 0
        meeting_minutes = 0
        for event in events:
            meeting_minutes += int(event["duration_minutes"])
            start_value = str(event["start"])
            start_at = _parse_datetime(start_value) if "T" in start_value else None
            if start_at and (start_at.hour < 9 or start_at.hour >= 17):
                after_hours_events += 1

        return ProviderContext(
            source=self.name,
            status="success",
            window_days=days,
            signals={
                "meeting_count": len(events),
                "meeting_hours": round(meeting_minutes / 60, 2),
                "after_hours_events": after_hours_events,
                "events": events,
            },
            coverage={
                "calendar_id": self.calendar_id,
                "event_count": len(events),
            },
            warnings=[],
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(20.0, connect=10.0),
        )


def sanitize_calendar_events(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe_events = []
    for item in items:
        title = item.get("summary") or "(untitled)"
        start = item.get("start") or {}
        end = item.get("end") or {}
        start_value = start.get("dateTime") or start.get("date") or ""
        duration_minutes = 0

        if start.get("dateTime") and end.get("dateTime"):
            start_at = _parse_datetime(start.get("dateTime"))
            end_at = _parse_datetime(end.get("dateTime"))
            if start_at and end_at and end_at >= start_at:
                duration_minutes = int((end_at - start_at).total_seconds() // 60)

        safe_events.append(
            {
                "title": title,
                "start": start_value,
                "duration_minutes": duration_minutes,
                "calendar_name": "",
                "category": _category(title),
            }
        )
    return safe_events


def _calendar_path(calendar_id: str) -> str:
    return quote(calendar_id, safe="")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _category(title: str) -> str:
    lowered = title.lower()
    if "review" in lowered:
        return "review"
    if "sync" in lowered:
        return "sync"
    if "interview" in lowered:
        return "interview"
    return "meeting"


__all__ = ["GoogleCalendarConnector", "sanitize_calendar_events"]
