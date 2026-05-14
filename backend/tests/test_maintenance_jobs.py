"""Maintenance job queue and worker."""

from __future__ import annotations

import json

import pytest

from app.agents import MemoryAgent
from app.core.memory_maintenance import drain_maintenance_jobs
from app.memory import checkin_repo, maintenance_repo, reflection_repo
from app.memory.maintenance_repo import JOB_DAILY_MEMORY, enqueue
from app.memory.schemas import CheckinIn, UserStateOut

pytestmark = pytest.mark.asyncio


async def test_enqueue_and_drain_daily_job(fake_llm) -> None:
    checkin_repo.add(CheckinIn(status="ok", did_today="did thing"))
    c = checkin_repo.latest()
    assert c is not None
    rid = reflection_repo.add(content="测试反思正文", kind="daily", insights=None)
    ref = reflection_repo.get_by_id(rid)
    assert ref is not None
    state = UserStateOut(
        focus=50,
        stress=40,
        burnout=30,
        momentum=50,
        confidence=50,
        motivation=50,
        weather_label="Recovery",
        rationale="ok",
    )
    enqueue(
        JOB_DAILY_MEMORY,
        {
            "session_id": "default",
            "for_date": c.date,
            "checkin_id": c.id,
            "reflection_id": ref.id,
            "state": state.model_dump(),
        },
    )
    fake_llm.queue_chat(json.dumps({"semantic": [], "milestones": [], "phases": []}))
    fake_llm.queue_chat(json.dumps({"patterns": []}))

    n = await drain_maintenance_jobs(MemoryAgent(fake_llm), max_jobs=5)
    assert n >= 1
    assert maintenance_repo.pending_count() == 0
