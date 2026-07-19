from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from weatherflow.activity import (
    ActivityWindowPlanner,
    SummaryFinality,
    SummaryTaskType,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def local(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=SHANGHAI).astimezone(UTC)


def test_window_planner_generates_all_fixed_shanghai_boundaries() -> None:
    planner = ActivityWindowPlanner()
    windows = planner.expected_windows(
        data_start=local(2026, 7, 13, 9),
        now=local(2026, 8, 3, 7),
    )

    six_hour = [item for item in windows if item.task_type is SummaryTaskType.STAGE_6H]
    daily = [item for item in windows if item.task_type is SummaryTaskType.DAILY_24H]
    weekly = [item for item in windows if item.task_type is SummaryTaskType.WEEKLY]
    biweekly = [item for item in windows if item.task_type is SummaryTaskType.BIWEEKLY]
    monthly = [item for item in windows if item.task_type is SummaryTaskType.MONTHLY]

    assert six_hour[0].window_start == local(2026, 7, 13, 6)
    assert six_hour[0].window_end == local(2026, 7, 13, 12)
    assert daily[0].window_start == local(2026, 7, 13, 6)
    assert daily[0].window_end == local(2026, 7, 14, 6)
    assert weekly[0].window_start == local(2026, 7, 13)
    assert weekly[0].window_end == local(2026, 7, 20)
    assert biweekly[0].window_end - biweekly[0].window_start == timedelta(days=14)
    assert monthly[0].window_start == local(2026, 7, 1)
    assert monthly[0].window_end == local(2026, 8, 1)


def test_latest_event_is_not_used_as_a_scheduler_cursor() -> None:
    planner = ActivityWindowPlanner()
    windows = planner.expected_windows(
        data_start=local(2026, 7, 15, 0),
        data_end=local(2026, 7, 15, 1),
        now=local(2026, 7, 16, 7),
    )

    assert any(
        item.task_type is SummaryTaskType.STAGE_6H
        and item.window_start == local(2026, 7, 16, 0)
        and item.window_end == local(2026, 7, 16, 6)
        for item in windows
    )


def test_six_hour_and_daily_tasks_can_share_the_0600_boundary() -> None:
    planner = ActivityWindowPlanner()
    windows = planner.expected_windows(
        data_start=local(2026, 7, 15, 6),
        now=local(2026, 7, 16, 7),
    )
    ending_at_six = [item for item in windows if item.window_end == local(2026, 7, 16, 6)]

    assert {item.task_type for item in ending_at_six} == {
        SummaryTaskType.STAGE_6H,
        SummaryTaskType.DAILY_24H,
    }
    assert len({item.id for item in ending_at_six}) == 2


def test_window_finality_respects_provisional_and_final_grace() -> None:
    planner = ActivityWindowPlanner()
    window = planner.window(
        SummaryTaskType.STAGE_6H,
        window_start=local(2026, 7, 16, 0),
        window_end=local(2026, 7, 16, 6),
    )

    assert planner.finality(window, now=window.window_end + timedelta(minutes=14)) is None
    assert (
        planner.finality(window, now=window.window_end + timedelta(minutes=15))
        is SummaryFinality.PROVISIONAL
    )
    assert (
        planner.finality(window, now=window.window_end + timedelta(minutes=60))
        is SummaryFinality.FINAL
    )


def test_dependencies_scale_by_interval_not_cartesian_product() -> None:
    planner = ActivityWindowPlanner()
    windows = planner.expected_windows(
        data_start=local(2024, 1, 1),
        now=local(2026, 1, 1, 1),
    )
    dependencies = planner.dependencies(windows)

    assert dependencies
    assert len(dependencies) < len(windows) * 200
