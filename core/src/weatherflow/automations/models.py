from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from ulid import ULID


class ScheduleKind(StrEnum):
    ONCE = "once"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKDAYS = "weekdays"
    WEEKLY = "weekly"


class AutomationStatus(StrEnum):
    ENABLED = "enabled"
    PAUSED = "paused"


class TriggerKind(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class RunLinkStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FAILED = "failed"


def require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


class ScheduleSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ScheduleKind
    timezone: str = Field(min_length=1, max_length=100)
    once_at: datetime | None = None
    minute: int | None = Field(default=None, ge=0, le=59)
    at_time: time | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("unknown IANA timezone") from error
        return value

    @field_validator("once_at")
    @classmethod
    def aware_once_at(cls, value: datetime | None) -> datetime | None:
        return require_aware(value) if value is not None else None

    @field_validator("at_time")
    @classmethod
    def local_time_only(cls, value: time | None) -> time | None:
        if value is not None and value.tzinfo is not None:
            raise ValueError("at_time must be a local wall-clock time")
        return value

    @model_validator(mode="after")
    def fields_match_kind(self) -> ScheduleSpec:
        if self.kind is ScheduleKind.ONCE:
            valid = self.once_at is not None and all(
                value is None for value in (self.minute, self.at_time, self.weekday)
            )
        elif self.kind is ScheduleKind.HOURLY:
            valid = self.minute is not None and all(
                value is None for value in (self.once_at, self.at_time, self.weekday)
            )
        elif self.kind in {ScheduleKind.DAILY, ScheduleKind.WEEKDAYS}:
            valid = (
                self.at_time is not None
                and self.once_at is None
                and self.minute is None
                and self.weekday is None
            )
        else:
            valid = (
                self.at_time is not None
                and self.weekday is not None
                and self.once_at is None
                and self.minute is None
            )
        if not valid:
            raise ValueError(f"schedule fields do not match {self.kind.value}")
        return self

    def next_after(self, after: datetime) -> datetime | None:
        """Return the first occurrence strictly after ``after`` in UTC.

        Local daily/weekly schedules run once per wall-clock day. A nonexistent
        spring-forward time is normalized through UTC to the first matching
        post-transition instant; an ambiguous time uses its first occurrence.
        """

        boundary = require_aware(after)
        if self.kind is ScheduleKind.ONCE:
            assert self.once_at is not None
            return self.once_at if self.once_at > boundary else None
        if self.kind is ScheduleKind.HOURLY:
            assert self.minute is not None
            zone = ZoneInfo(self.timezone)
            local_boundary = boundary.astimezone(zone)
            local_candidate = local_boundary.replace(
                minute=self.minute,
                second=0,
                microsecond=0,
                fold=0,
            )
            candidate = local_candidate.astimezone(UTC)
            if candidate <= boundary:
                next_hour = local_candidate.replace(tzinfo=None) + timedelta(hours=1)
                candidate = next_hour.replace(tzinfo=zone, fold=0).astimezone(UTC)
            return candidate

        zone = ZoneInfo(self.timezone)
        local_boundary = boundary.astimezone(zone)
        assert self.at_time is not None
        for offset in range(8):
            local_date = local_boundary.date() + timedelta(days=offset)
            if not self._date_matches(local_date):
                continue
            candidate = self._local_occurrence(local_date, zone)
            if candidate > boundary:
                return candidate
        raise RuntimeError("recurring schedule did not produce an occurrence")

    def _date_matches(self, candidate: date) -> bool:
        if self.kind is ScheduleKind.WEEKDAYS:
            return candidate.weekday() < 5
        if self.kind is ScheduleKind.WEEKLY:
            return candidate.weekday() == self.weekday
        return True

    def _local_occurrence(self, local_date: date, zone: ZoneInfo) -> datetime:
        assert self.at_time is not None
        local = datetime.combine(local_date, self.at_time).replace(tzinfo=zone, fold=0)
        return local.astimezone(UTC)


class Automation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    workspace_id: str
    name: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=20_000)
    schedule: ScheduleSpec
    status: AutomationStatus = AutomationStatus.ENABLED
    next_run_at: datetime | None
    last_run_at: datetime | None = None
    version: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime

    @field_validator("next_run_at", "last_run_at", "created_at", "updated_at")
    @classmethod
    def aware_timestamps(cls, value: datetime | None) -> datetime | None:
        return require_aware(value) if value is not None else None

    @classmethod
    def new(
        cls,
        *,
        workspace_id: str,
        name: str,
        prompt: str,
        schedule: ScheduleSpec,
        now: datetime,
    ) -> Automation:
        observed = require_aware(now)
        return cls(
            id=str(ULID()),
            workspace_id=workspace_id,
            name=name,
            prompt=prompt,
            schedule=schedule,
            next_run_at=schedule.next_after(observed - timedelta(microseconds=1)),
            created_at=observed,
            updated_at=observed,
        )


class AutomationRunLink(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    automation_id: str
    workspace_id: str
    trigger: TriggerKind
    scheduled_for: datetime
    client_request_id: str
    status: RunLinkStatus = RunLinkStatus.PENDING
    run_id: str | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("scheduled_for", "created_at", "updated_at")
    @classmethod
    def aware_link_timestamps(cls, value: datetime) -> datetime:
        return require_aware(value)

    @classmethod
    def scheduled(
        cls,
        *,
        automation: Automation,
        scheduled_for: datetime,
        now: datetime,
    ) -> AutomationRunLink:
        occurrence = require_aware(scheduled_for)
        observed = require_aware(now)
        return cls(
            id=str(ULID()),
            automation_id=automation.id,
            workspace_id=automation.workspace_id,
            trigger=TriggerKind.SCHEDULED,
            scheduled_for=occurrence,
            client_request_id=(f"automation:{automation.id}:scheduled:{occurrence.isoformat()}"),
            created_at=observed,
            updated_at=observed,
        )

    @classmethod
    def manual(cls, *, automation: Automation, now: datetime) -> AutomationRunLink:
        observed = require_aware(now)
        link_id = str(ULID())
        return cls(
            id=link_id,
            automation_id=automation.id,
            workspace_id=automation.workspace_id,
            trigger=TriggerKind.MANUAL,
            scheduled_for=observed,
            client_request_id=f"automation:{automation.id}:manual:{link_id}",
            created_at=observed,
            updated_at=observed,
        )
