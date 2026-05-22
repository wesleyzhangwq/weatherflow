"""Calendar MCP tool implementations."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_WRITE_TOOLS_ENV = "WF_MCP_WRITE_TOOLS_ENABLED"


def _write_tools_enabled() -> bool:
    return os.environ.get(_WRITE_TOOLS_ENV, "false").lower() in ("true", "1", "yes")


def _load_access_token() -> str:
    """Load Calendar access token from token file or env var."""
    token_file = os.environ.get("GOOGLE_CALENDAR_TOKEN_FILE", "")
    if token_file.strip():
        from pathlib import Path
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        _SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
        path = Path(token_file).expanduser()
        if path.is_file():
            try:
                creds = Credentials.from_authorized_user_file(str(path), _SCOPES)
                if creds.valid and creds.token:
                    return str(creds.token)
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    path.write_text(creds.to_json(), encoding="utf-8")
                    if creds.token:
                        return str(creds.token)
            except Exception:
                logger.exception("Failed to load Google Calendar token file.")

    token = os.environ.get("GOOGLE_CALENDAR_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Google Calendar access token is not configured.")
    return token


def _build_client(base_url: str = "https://www.googleapis.com/calendar/v3") -> httpx.AsyncClient:
    token = _load_access_token()
    return httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        timeout=httpx.Timeout(20.0, connect=10.0),
    )


def _calendar_path(calendar_id: str) -> str:
    from urllib.parse import quote
    return quote(calendar_id, safe="")


def _category(title: str) -> str:
    lowered = title.lower()
    if "review" in lowered:
        return "review"
    if "sync" in lowered:
        return "sync"
    if "interview" in lowered:
        return "interview"
    return "meeting"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sanitize_events(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe = []
    for item in items:
        title = item.get("summary") or "(untitled)"
        start = item.get("start") or {}
        end = item.get("end") or {}
        start_value = start.get("dateTime") or start.get("date") or ""
        end_value = end.get("dateTime") or end.get("date") or ""
        duration_minutes = 0

        start_dt = _parse_dt(start.get("dateTime"))
        end_dt = _parse_dt(end.get("dateTime"))
        if start_dt and end_dt and end_dt >= start_dt:
            duration_minutes = int((end_dt - start_dt).total_seconds() // 60)

        safe.append({
            "id": item.get("id", ""),
            "title": title,
            "start": start_value,
            "end": end_value,
            "duration_minutes": duration_minutes,
            "category": _category(title),
        })
    return safe


async def search_events(
    start_time: str,
    end_time: str,
    keyword: Optional[str] = None,
    calendar_id: str = "primary",
    max_results: int = 50,
    *,
    _client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    async with (_client or _build_client()) as client:
        r = await client.get(
            f"/calendars/{_calendar_path(calendar_id)}/events",
            params={
                "timeMin": start_time,
                "timeMax": end_time,
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": max_results,
            },
        )
        r.raise_for_status()
        data = r.json()

    events = _sanitize_events(data.get("items") or [])

    if keyword:
        kw = keyword.lower()
        events = [e for e in events if kw in e["title"].lower()]

    return {
        "events": events,
        "coverage": {
            "calendar_id": calendar_id,
            "event_count": len(events),
        },
    }


async def find_free_slots(
    start_time: str,
    end_time: str,
    min_duration_minutes: int = 45,
    calendar_id: str = "primary",
    workday_start: str = "09:00",
    workday_end: str = "18:00",
    *,
    _client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    result = await search_events(
        start_time=start_time,
        end_time=end_time,
        calendar_id=calendar_id,
        max_results=250,
        _client=_client,
    )
    events = result["events"]

    window_start = _parse_dt(start_time)
    window_end = _parse_dt(end_time)
    if not window_start or not window_end:
        return {"slots": []}

    tz = window_start.tzinfo

    def _workday_bound(date: datetime, time_str: str) -> datetime:
        h, m = (int(x) for x in time_str.split(":"))
        return date.replace(hour=h, minute=m, second=0, microsecond=0)

    busy: list[tuple[datetime, datetime]] = []
    for ev in events:
        s = _parse_dt(ev["start"])
        e = _parse_dt(ev["end"])
        if s and e and ev["duration_minutes"] > 0:
            busy.append((s, e))

    busy.sort(key=lambda x: x[0])

    merged: list[tuple[datetime, datetime]] = []
    for s, e in busy:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    slots = []
    current_day = window_start.date()
    end_day = window_end.date()

    while current_day <= end_day:
        day_dt = window_start.replace(
            year=current_day.year, month=current_day.month, day=current_day.day,
            hour=0, minute=0, second=0, microsecond=0,
        )
        day_start = _workday_bound(day_dt, workday_start)
        day_end = _workday_bound(day_dt, workday_end)
        day_start = max(day_start, window_start)
        day_end = min(day_end, window_end)

        if day_start >= day_end:
            current_day += timedelta(days=1)
            continue

        free_start = day_start
        for b_start, b_end in merged:
            if b_end <= free_start or b_start >= day_end:
                continue
            if b_start > free_start:
                slot_end = min(b_start, day_end)
                duration = int((slot_end - free_start).total_seconds() // 60)
                if duration >= min_duration_minutes:
                    slots.append({
                        "start": free_start.isoformat(),
                        "end": slot_end.isoformat(),
                        "duration_minutes": duration,
                    })
            free_start = max(free_start, b_end)

        if free_start < day_end:
            duration = int((day_end - free_start).total_seconds() // 60)
            if duration >= min_duration_minutes:
                slots.append({
                    "start": free_start.isoformat(),
                    "end": day_end.isoformat(),
                    "duration_minutes": duration,
                })

        current_day += timedelta(days=1)

    return {"slots": slots}


async def create_event(
    title: str,
    start_time: str,
    end_time: str,
    calendar_id: str = "primary",
    description: str = "Created by WeatherFlow",
    dry_run: bool = False,
    *,
    _client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    if not _write_tools_enabled() and not dry_run:
        raise PermissionError("Calendar write tools are disabled.")

    payload = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_time},
        "end": {"dateTime": end_time},
    }

    if dry_run:
        return {
            "created": False,
            "dry_run": True,
            "event": {"title": title, "start": start_time, "end": end_time},
        }

    async with (_client or _build_client()) as client:
        r = await client.post(
            f"/calendars/{_calendar_path(calendar_id)}/events",
            json=payload,
        )
        r.raise_for_status()
        data = r.json()

    return {
        "created": True,
        "event": {
            "id": data.get("id", ""),
            "title": data.get("summary", title),
            "html_link": data.get("htmlLink", ""),
        },
    }


async def create_focus_block(
    title: str,
    duration_minutes: int,
    date: str,
    preferred_time: str = "morning",
    priority: str = "high",
    calendar_id: str = "primary",
    dry_run: bool = False,
    *,
    _client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    if not _write_tools_enabled() and not dry_run:
        raise PermissionError("Calendar write tools are disabled.")

    _TIME_WINDOWS = {
        "morning": ("09:00", "12:00"),
        "afternoon": ("13:00", "18:00"),
        "evening": ("18:00", "21:00"),
    }
    pref_start, pref_end = _TIME_WINDOWS.get(preferred_time, ("09:00", "18:00"))

    day_start = f"{date}T00:00:00+00:00"
    day_end = f"{date}T23:59:59+00:00"

    pref_window_start = f"{date}T{pref_start}:00+00:00"
    pref_window_end = f"{date}T{pref_end}:00+00:00"

    pref_slots_result = await find_free_slots(
        start_time=pref_window_start,
        end_time=pref_window_end,
        min_duration_minutes=duration_minutes,
        calendar_id=calendar_id,
        workday_start=pref_start,
        workday_end=pref_end,
        _client=_client,
    )
    pref_slots = pref_slots_result.get("slots", [])

    selected_slot = None
    if pref_slots:
        selected_slot = pref_slots[0]
    else:
        full_slots_result = await find_free_slots(
            start_time=day_start,
            end_time=day_end,
            min_duration_minutes=duration_minutes,
            calendar_id=calendar_id,
            workday_start="00:00",
            workday_end="23:59",
            _client=_client,
        )
        full_slots = full_slots_result.get("slots", [])
        if full_slots:
            selected_slot = full_slots[0]

    if not selected_slot:
        return {"created": False, "reason": "No available slot found for the requested duration."}

    slot_start = selected_slot["start"]
    slot_end_dt = _parse_dt(slot_start)
    if not slot_end_dt:
        return {"created": False, "reason": "Failed to parse selected slot start time."}
    slot_end = (slot_end_dt + timedelta(minutes=duration_minutes)).isoformat()

    event_result = await create_event(
        title=title,
        start_time=slot_start,
        end_time=slot_end,
        calendar_id=calendar_id,
        description="Created by WeatherFlow",
        dry_run=dry_run,
        _client=_client,
    )

    return {
        **event_result,
        "selected_slot": {
            "start": slot_start,
            "end": slot_end,
        },
    }


__all__ = [
    "search_events",
    "find_free_slots",
    "create_event",
    "create_focus_block",
]
