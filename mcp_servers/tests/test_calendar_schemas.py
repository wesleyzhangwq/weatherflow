from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcp_servers.weatherflow_calendar.schemas import (
    CalendarCreateEventInput,
    CalendarCreateFocusBlockInput,
    CalendarFindFreeSlotsInput,
    CalendarSearchEventsInput,
)


def test_search_events_valid() -> None:
    s = CalendarSearchEventsInput(
        start_time="2026-05-22T09:00:00+08:00",
        end_time="2026-05-22T18:00:00+08:00",
    )
    assert s.calendar_id == "primary"
    assert s.max_results == 50


def test_search_events_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError, match="end_time"):
        CalendarSearchEventsInput(
            start_time="2026-05-22T18:00:00+08:00",
            end_time="2026-05-22T09:00:00+08:00",
        )


def test_find_free_slots_rejects_zero_duration() -> None:
    with pytest.raises(ValidationError, match="min_duration_minutes"):
        CalendarFindFreeSlotsInput(
            start_time="2026-05-22T09:00:00+08:00",
            end_time="2026-05-22T18:00:00+08:00",
            min_duration_minutes=0,
        )


def test_find_free_slots_rejects_negative_duration() -> None:
    with pytest.raises(ValidationError, match="min_duration_minutes"):
        CalendarFindFreeSlotsInput(
            start_time="2026-05-22T09:00:00+08:00",
            end_time="2026-05-22T18:00:00+08:00",
            min_duration_minutes=-10,
        )


def test_create_event_valid() -> None:
    e = CalendarCreateEventInput(
        title="Planning",
        start_time="2026-05-23T10:00:00+08:00",
        end_time="2026-05-23T11:00:00+08:00",
    )
    assert e.dry_run is False
    assert e.description == "Created by WeatherFlow"


def test_create_event_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        CalendarCreateEventInput(
            title="Bad",
            start_time="2026-05-23T11:00:00+08:00",
            end_time="2026-05-23T10:00:00+08:00",
        )


def test_create_focus_block_valid_preferred_times() -> None:
    for pref in ("morning", "afternoon", "evening"):
        f = CalendarCreateFocusBlockInput(
            title="Deep Work",
            duration_minutes=90,
            preferred_time=pref,
            date="2026-05-23",
        )
        assert f.preferred_time == pref


def test_create_focus_block_rejects_invalid_preferred_time() -> None:
    with pytest.raises(ValidationError):
        CalendarCreateFocusBlockInput(
            title="Deep Work",
            duration_minutes=90,
            preferred_time="night",
            date="2026-05-23",
        )


def test_create_focus_block_rejects_zero_duration() -> None:
    with pytest.raises(ValidationError, match="duration_minutes"):
        CalendarCreateFocusBlockInput(
            title="Deep Work",
            duration_minutes=0,
            date="2026-05-23",
        )
