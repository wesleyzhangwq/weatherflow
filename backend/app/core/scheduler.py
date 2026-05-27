"""APScheduler wiring — T2 every 6h + DelayedMemoryWriter every 12h heartbeat.

Per §8.1, T2 fires at fixed local-time slots (default 00/06/12/18). The user
activity level is irrelevant. The DelayedMemoryWriter has its own heartbeat
(§9.2) as a safety net for edge cases.
"""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _make_tz(settings: Settings):
    if settings.timezone in ("", "local"):
        return None
    return settings.timezone


def build_scheduler(settings: Optional[Settings] = None) -> Optional[AsyncIOScheduler]:
    s = settings or get_settings()
    if not s.scheduler_enabled:
        logger.info("Scheduler disabled by config.")
        return None

    scheduler = AsyncIOScheduler(timezone=_make_tz(s))

    hours = ",".join(str(h) for h in s.parsed_scheduled_check_hours)
    scheduler.add_job(
        _scheduled_check_job,
        trigger=CronTrigger(hour=hours, minute=0, timezone=_make_tz(s)),
        id="scheduled_check",
        replace_existing=True,
        misfire_grace_time=900,
    )
    logger.info("Scheduled T2 check at hours: %s (local)", hours)

    scheduler.add_job(
        _delayed_memory_writer_job,
        trigger=IntervalTrigger(hours=s.memory_writer_interval_hours),
        id="delayed_memory_writer_heartbeat",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info(
        "Scheduled DelayedMemoryWriter heartbeat every %dh",
        s.memory_writer_interval_hours,
    )
    return scheduler


# --------------------------------------------------------------------------- jobs


async def _scheduled_check_job() -> None:
    try:
        from app.core import scheduled_check
        from app.core.llm import build_llm_client

        llm = build_llm_client()
        try:
            result = await scheduled_check.run(llm=llm)
            logger.info("scheduled_check result: %s", result)
        finally:
            await llm.aclose()
    except Exception:
        logger.exception("scheduled_check job failed")


async def _delayed_memory_writer_job() -> None:
    try:
        from app.memory.delayed_writer import maybe_update

        await maybe_update()
    except Exception:
        logger.exception("delayed_memory_writer job failed")


__all__ = ["build_scheduler"]
