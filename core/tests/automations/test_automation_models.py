from datetime import UTC, datetime, time

import pytest
from pydantic import ValidationError

from weatherflow.automations import ScheduleKind, ScheduleSpec


def test_schedule_spec_calculates_supported_recurrences() -> None:
    after = datetime(2026, 7, 13, 23, 30, tzinfo=UTC)

    assert ScheduleSpec(
        kind=ScheduleKind.HOURLY,
        timezone="Asia/Shanghai",
        minute=45,
    ).next_after(after) == datetime(2026, 7, 13, 23, 45, tzinfo=UTC)
    assert ScheduleSpec(
        kind=ScheduleKind.DAILY,
        timezone="Asia/Shanghai",
        at_time=time(8, 0),
    ).next_after(after) == datetime(2026, 7, 14, 0, 0, tzinfo=UTC)
    assert ScheduleSpec(
        kind=ScheduleKind.WEEKDAYS,
        timezone="Asia/Shanghai",
        at_time=time(8, 0),
    ).next_after(datetime(2026, 7, 17, 1, 0, tzinfo=UTC)) == datetime(2026, 7, 20, 0, 0, tzinfo=UTC)
    assert ScheduleSpec(
        kind=ScheduleKind.WEEKLY,
        timezone="Asia/Shanghai",
        weekday=4,
        at_time=time(16, 0),
    ).next_after(datetime(2026, 7, 17, 8, 0, tzinfo=UTC)) == datetime(2026, 7, 24, 8, 0, tzinfo=UTC)


def test_daily_schedule_runs_once_across_dst_transitions() -> None:
    spring_schedule = ScheduleSpec(
        kind=ScheduleKind.DAILY,
        timezone="America/New_York",
        at_time=time(2, 30),
    )
    fall_schedule = spring_schedule.model_copy(update={"at_time": time(1, 30)})

    spring = spring_schedule.next_after(datetime(2026, 3, 8, 6, 59, tzinfo=UTC))
    fall_first = fall_schedule.next_after(datetime(2026, 11, 1, 4, 0, tzinfo=UTC))
    fall_next = fall_schedule.next_after(datetime(2026, 11, 1, 5, 45, tzinfo=UTC))

    assert spring == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    assert fall_first == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert fall_next == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)


def test_once_and_invalid_schedule_fields_fail_closed() -> None:
    once = ScheduleSpec(
        kind=ScheduleKind.ONCE,
        timezone="UTC",
        once_at=datetime(2026, 7, 14, 6, 0, tzinfo=UTC),
    )

    assert once.next_after(datetime(2026, 7, 14, 5, 59, tzinfo=UTC)) == once.once_at
    assert once.next_after(once.once_at) is None
    with pytest.raises(ValidationError):
        ScheduleSpec(kind=ScheduleKind.ONCE, timezone="UTC")
    with pytest.raises(ValidationError):
        ScheduleSpec(
            kind=ScheduleKind.DAILY,
            timezone="Not/AZone",
            at_time=time(8, 0),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        once.next_after(datetime(2026, 7, 14, 5, 59))
