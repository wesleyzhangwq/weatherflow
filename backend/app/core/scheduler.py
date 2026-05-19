"""Background scheduler — keeps WeatherFlow's "low-friction companionship"
promise by running daily/weekly reflections without the user having to ask.

Cron-string shapes accepted (kept tiny on purpose, no full cron grammar):
    "22:00"             -> daily at 22:00
    "sun:21:00"         -> weekly, Sunday 21:00
    ""  / "off"         -> disabled

Configure via env:
    SCHEDULER_ENABLED=true
    EVENING_REFLECTION_CRON=22:00
    WEEKLY_REVIEW_CRON=sun:21:00
    SCHEDULER_TIMEZONE=local | UTC | Asia/Shanghai | ...
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings

import logging

logger = logging.getLogger(__name__)

_DOW_MAP = {
    "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu",
    "fri": "fri", "sat": "sat", "sun": "sun",
}
_DAILY_RE = re.compile(r"^([0-2]?\d):([0-5]\d)$")
_WEEKLY_RE = re.compile(r"^([a-zA-Z]{3}):([0-2]?\d):([0-5]\d)$")


def parse_trigger(spec: str, *, timezone: Optional[str] = None) -> Optional[CronTrigger]:
    """Parse a tiny cron-spec into an APScheduler CronTrigger.

    Returns ``None`` if the spec disables scheduling.
    """
    if not spec or spec.strip().lower() in {"off", "disabled", "no", "none"}:
        return None

    tz = None if timezone in (None, "", "local") else timezone

    s = spec.strip().lower()
    m = _WEEKLY_RE.match(s)
    if m:
        dow_raw, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
        dow = _DOW_MAP.get(dow_raw)
        if not dow:
            raise ValueError(f"unknown day-of-week: {dow_raw}")
        return CronTrigger(day_of_week=dow, hour=hh, minute=mm, timezone=tz)

    m = _DAILY_RE.match(s)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        return CronTrigger(hour=hh, minute=mm, timezone=tz)

    raise ValueError(f"unrecognised cron spec: {spec!r}")


def build_scheduler(
    settings: Settings,
    *,
    daily_job: Callable[[], "object"],
    weekly_job: Callable[[], "object"],
) -> Optional[AsyncIOScheduler]:
    """Build & configure a scheduler. Returns None if disabled."""
    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled by config.")
        return None

    daily_trigger = parse_trigger(
        settings.evening_reflection_cron, timezone=settings.scheduler_timezone
    )
    weekly_trigger = parse_trigger(
        settings.weekly_review_cron, timezone=settings.scheduler_timezone
    )
    if daily_trigger is None and weekly_trigger is None:
        logger.info("Scheduler enabled but no triggers configured.")
        return None

    scheduler = AsyncIOScheduler(timezone=None if settings.scheduler_timezone == "local" else settings.scheduler_timezone)
    if daily_trigger is not None:
        scheduler.add_job(
            daily_job,
            trigger=daily_trigger,
            id="evening_reflection",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Scheduled evening reflection: %s", settings.evening_reflection_cron)
    if weekly_trigger is not None:
        scheduler.add_job(
            weekly_job,
            trigger=weekly_trigger,
            id="weekly_review",
            replace_existing=True,
            misfire_grace_time=6 * 3600,
        )
        logger.info("Scheduled weekly review: %s", settings.weekly_review_cron)
    return scheduler


__all__ = ["build_scheduler", "parse_trigger"]
