"""Pydantic models for Calendar MCP tool inputs and outputs."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, field_validator, model_validator


class CalendarSearchEventsInput(BaseModel):
    start_time: str
    end_time: str
    keyword: Optional[str] = None
    calendar_id: str = "primary"
    max_results: int = 50

    @model_validator(mode="after")
    def end_after_start(self) -> "CalendarSearchEventsInput":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class CalendarFindFreeSlotsInput(BaseModel):
    start_time: str
    end_time: str
    min_duration_minutes: int = 45
    calendar_id: str = "primary"
    workday_start: str = "09:00"
    workday_end: str = "18:00"

    @model_validator(mode="after")
    def end_after_start(self) -> "CalendarFindFreeSlotsInput":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self

    @field_validator("min_duration_minutes")
    @classmethod
    def positive_duration(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("min_duration_minutes must be > 0")
        return v


class CalendarCreateEventInput(BaseModel):
    title: str
    start_time: str
    end_time: str
    calendar_id: str = "primary"
    description: str = "Created by WeatherFlow"
    dry_run: bool = False

    @model_validator(mode="after")
    def end_after_start(self) -> "CalendarCreateEventInput":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class CalendarCreateFocusBlockInput(BaseModel):
    title: str
    duration_minutes: int
    preferred_time: Literal["morning", "afternoon", "evening"] = "morning"
    priority: str = "high"
    date: str
    calendar_id: str = "primary"
    dry_run: bool = False

    @field_validator("duration_minutes")
    @classmethod
    def positive_duration(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("duration_minutes must be > 0")
        return v


class CalendarUpdateEventInput(BaseModel):
    event_id: str
    calendar_id: str = "primary"
    title: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    description: Optional[str] = None
    dry_run: bool = False

    @field_validator("event_id")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("event_id must be non-empty")
        return v


class CalendarDeleteEventInput(BaseModel):
    event_id: str
    calendar_id: str = "primary"
    dry_run: bool = False

    @field_validator("event_id")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("event_id must be non-empty")
        return v


class CalendarEventRead(BaseModel):
    id: str = ""
    title: str
    start: str
    end: str = ""
    duration_minutes: int
    category: str = "meeting"


class CalendarFreeSlot(BaseModel):
    start: str
    end: str
    duration_minutes: int


__all__ = [
    "CalendarSearchEventsInput",
    "CalendarFindFreeSlotsInput",
    "CalendarCreateEventInput",
    "CalendarCreateFocusBlockInput",
    "CalendarUpdateEventInput",
    "CalendarDeleteEventInput",
    "CalendarEventRead",
    "CalendarFreeSlot",
]
