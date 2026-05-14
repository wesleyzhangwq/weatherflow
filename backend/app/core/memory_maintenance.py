"""Execute queued memory maintenance jobs."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.memory_agent import MemoryAgent
from app.memory import checkin_repo, reflection_repo
from app.memory.maintenance_repo import (
    JOB_DAILY_MEMORY,
    JOB_WEEKLY_MEMORY,
    MaintenanceJob,
    claim_next,
    mark_done,
    mark_failed,
)
from app.memory.schemas import UserStateOut

logger = logging.getLogger(__name__)


def _event_lines_for_day(session_id: str, for_date: str, limit: int = 25) -> list[str]:
    from app.memory import events_repo

    evs = events_repo.recent(limit=160, session_id=session_id)
    lines: list[str] = []
    for e in evs:
        ts = e.timestamp[:10] if e.timestamp else ""
        if ts != for_date:
            continue
        lines.append(f"{e.type}: {(e.content or '').strip()[:200]}")
        if len(lines) >= limit:
            break
    return lines


async def _run_daily_payload(memory_agent: MemoryAgent, payload: dict[str, Any]) -> None:
    session_id = str(payload.get("session_id") or "default")
    for_date = str(payload.get("for_date") or "")
    reflection_id = int(payload["reflection_id"])
    state_raw = payload.get("state") or {}
    state = UserStateOut.model_validate(state_raw)
    reflection = reflection_repo.get_by_id(reflection_id)
    if reflection is None:
        raise RuntimeError(f"reflection {reflection_id} not found")

    cid = payload.get("checkin_id")
    if cid is not None:
        rec = checkin_repo.get_by_id(int(cid))
        if rec is not None:
            await memory_agent.ingest_checkin(rec)

    await memory_agent.ingest_reflection(reflection)

    event_lines = _event_lines_for_day(session_id, for_date)
    await memory_agent.write_daily_markdown(
        for_date=for_date,
        state=state,
        reflection=reflection,
        event_lines=event_lines or None,
        semantic_hints=None,
    )

    recent_checkins = checkin_repo.recent(limit=7)
    recent_refs = reflection_repo.recent(limit=5)
    try:
        await memory_agent.extract(
            recent_checkins=recent_checkins,
            recent_reflections=recent_refs,
        )
    except Exception:
        logger.exception("maintenance extract failed")

    await memory_agent.compress_to_long_term(
        for_date=for_date,
        reflection=reflection,
        extra_context="",
    )


async def _run_weekly_payload(memory_agent: MemoryAgent, payload: dict[str, Any]) -> None:
    reflection_id = int(payload["reflection_id"])
    reflection = reflection_repo.get_by_id(reflection_id)
    if reflection is None:
        raise RuntimeError(f"reflection {reflection_id} not found")

    bullets_raw = payload.get("summary_bullets") or []
    summary_bullets = [str(b) for b in bullets_raw if str(b).strip()]
    if not summary_bullets:
        summary_bullets = [reflection.content[:240]]

    await memory_agent.ingest_reflection(reflection)
    await memory_agent.append_weekly_markdown(
        reflection=reflection,
        summary_bullets=summary_bullets,
    )

    from datetime import date

    for_date = date.today().isoformat()
    await memory_agent.compress_to_long_term(
        for_date=for_date,
        reflection=reflection,
        extra_context="weekly_review",
    )

    recent_checkins = checkin_repo.recent(limit=14)
    recent_refs = reflection_repo.recent(limit=10)
    try:
        await memory_agent.extract(
            recent_checkins=recent_checkins,
            recent_reflections=recent_refs,
        )
    except Exception:
        logger.exception("weekly maintenance extract failed")

    try:
        await memory_agent.refresh_profiles()
    except Exception:
        logger.exception("weekly maintenance profile refresh failed")


async def execute_job(memory_agent: MemoryAgent, job: MaintenanceJob) -> None:
    if job.type == JOB_DAILY_MEMORY:
        await _run_daily_payload(memory_agent, job.payload)
    elif job.type == JOB_WEEKLY_MEMORY:
        await _run_weekly_payload(memory_agent, job.payload)
    else:
        raise RuntimeError(f"unknown maintenance job type: {job.type}")


async def drain_maintenance_jobs(
    memory_agent: MemoryAgent,
    *,
    max_jobs: int = 64,
) -> int:
    """Process pending jobs until empty or ``max_jobs`` reached."""
    done = 0
    for _ in range(max_jobs):
        job = claim_next()
        if job is None:
            break
        try:
            await execute_job(memory_agent, job)
            mark_done(job.id)
        except Exception as exc:
            logger.exception("maintenance job %s failed", job.id)
            mark_failed(job.id, str(exc))
        done += 1
    return done


__all__ = [
    "drain_maintenance_jobs",
    "execute_job",
    "JOB_DAILY_MEMORY",
    "JOB_WEEKLY_MEMORY",
]
