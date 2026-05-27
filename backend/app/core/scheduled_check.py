"""T2 定时检查 — runs every 6 hours.

Flow (§8.2):
  1. Pull calendar (MCP) → calendar_snapshot in L1
  2. Pull github (MCP)   → github_snapshot in L1
  3. LLM summarize       → evidence_summary in L1
  4. generate_hypothesis(trigger=summary_id, mode="background")
"""

from __future__ import annotations

import logging
from typing import Optional

from app.config import get_settings
from app.core import evidence_summarizer
from app.core.llm import LLMClient
from app.core.orchestrator import generate_hypothesis
from app.memory import event_log
from app.providers import calendar as calendar_provider
from app.providers import github as github_provider

logger = logging.getLogger(__name__)


async def run(
    *,
    llm: LLMClient,
    user_id: Optional[str] = None,
) -> dict:
    settings = get_settings()
    uid = user_id or settings.default_user_id

    calendar = await _safe(calendar_provider.fetch_snapshot, label="calendar")
    cal_id = None
    if calendar:
        cal_id = event_log.append(
            type="calendar_snapshot", payload=calendar.model_dump(), user_id=uid
        )

    github = await _safe(github_provider.fetch_snapshot, label="github")
    gh_id = None
    if github:
        gh_id = event_log.append(
            type="github_snapshot", payload=github.model_dump(), user_id=uid
        )

    if calendar is None and github is None:
        logger.warning("Scheduled check: both providers failed; aborting.")
        return {"status": "skipped", "reason": "providers_failed"}

    summary = await evidence_summarizer.summarize(
        llm=llm,
        calendar=calendar or _empty_calendar(),
        github=github or _empty_github(),
    )
    refs = {"sources": [x for x in (cal_id, gh_id) if x]}
    summary_id = event_log.append(
        type="evidence_summary",
        payload=summary.model_dump(),
        user_id=uid,
        refs=refs,
    )

    hyp_id, hyp = await generate_hypothesis(
        trigger_event_id=summary_id,
        mode="background",
        llm=llm,
        user_id=uid,
    )
    return {
        "status": "ok",
        "calendar_snapshot_id": cal_id,
        "github_snapshot_id": gh_id,
        "evidence_summary_id": summary_id,
        "hypothesis_id": hyp_id,
        "label": hyp.label,
        "confidence": hyp.confidence,
    }


async def _safe(fn, *, label: str):
    try:
        return await fn()
    except Exception:
        logger.exception("Scheduled-check %s fetch failed", label)
        return None


def _empty_calendar():
    from app.memory.schemas import CalendarSnapshotPayload

    return CalendarSnapshotPayload(events=[], window_start="", window_end="")


def _empty_github():
    from app.memory.schemas import GithubSnapshotPayload

    return GithubSnapshotPayload()


__all__ = ["run"]
