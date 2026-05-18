"""Dev review API orchestration."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app.agents.dev_review_agent import DevReviewAgent
from app.config import get_settings
from app.core.agent_runs import AgentRunTracker
from app.mcp.github import GithubConnector, normalize_github_summary
from app.mcp.google_calendar import GoogleCalendarConnector
from app.memory import dev_review_repo
from app.memory.schemas import (
    AgentRunCreate,
    DevReviewCreate,
    DevReviewRecord,
    DevReviewRunRequest,
    ProviderContext,
)
from app.routers._deps import get_llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dev-review", tags=["dev-review"])

_NO_PROVIDER_MESSAGE = "Configure at least one provider: GitHub or Google Calendar."


@router.post("/runs", response_model=DevReviewRecord)
async def create_dev_review_run(
    payload: DevReviewRunRequest,
    request: Request,
) -> DevReviewRecord:
    settings = get_settings()
    run_id = dev_review_repo.create_run(
        AgentRunCreate(
            input={
                "window_days": payload.window_days,
                "providers": payload.providers,
            }
        )
    )
    tracker = AgentRunTracker(run_id)
    contexts: list[ProviderContext] = []

    if "github" in payload.providers:
        if not settings.github_token.strip():
            tracker.step("github", "skipped", "GitHub access is not configured.")
        else:
            try:
                summary = await GithubConnector(settings.github_token).fetch(
                    days=payload.window_days
                )
                context = normalize_github_summary(
                    summary,
                    window_days=payload.window_days,
                )
                contexts.append(context)
                tracker.step(
                    "github",
                    context.status,
                    "Fetched recent GitHub activity.",
                    metadata={"coverage": context.coverage},
                )
            except Exception:
                logger.exception("GitHub dev review provider failed.")
                tracker.step("github", "failed", "GitHub provider failed.")

    if "google_calendar" in payload.providers:
        if not settings.google_calendar_access_token.strip():
            tracker.step(
                "google_calendar",
                "skipped",
                "Google Calendar access is not configured.",
            )
        else:
            try:
                context = await GoogleCalendarConnector(
                    settings.google_calendar_access_token,
                    calendar_id=settings.google_calendar_calendar_id,
                    base_url=settings.google_calendar_base_url,
                ).fetch(days=payload.window_days)
                contexts.append(context)
                tracker.step(
                    "google_calendar",
                    context.status,
                    "Fetched recent Google Calendar activity.",
                    metadata={"coverage": context.coverage},
                )
            except Exception:
                logger.exception("Google Calendar dev review provider failed.")
                tracker.step(
                    "google_calendar",
                    "failed",
                    "Google Calendar provider failed.",
                )

    if not _has_usable_context(contexts):
        tracker.fail(_NO_PROVIDER_MESSAGE)
        raise HTTPException(status_code=400, detail=_NO_PROVIDER_MESSAGE)

    review = await DevReviewAgent(get_llm(request)).synthesize(
        payload.window_days,
        contexts,
    )
    review_id = dev_review_repo.create_review(_with_run_id(review, run_id))
    tracker.finish()
    persisted = dev_review_repo.get_review(review_id)
    if persisted is None:
        raise HTTPException(status_code=500, detail="Dev review was not persisted.")
    return persisted


@router.get("/runs/latest", response_model=DevReviewRecord | None)
def latest_dev_review_run() -> DevReviewRecord | None:
    return dev_review_repo.latest_review()


@router.get("/runs/{run_id}", response_model=DevReviewRecord)
def dev_review_run(run_id: int) -> DevReviewRecord:
    try:
        review = dev_review_repo.latest_review_for_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Dev review run not found.") from exc
    if review is None:
        raise HTTPException(status_code=404, detail="Dev review run not found.")
    return review


def _has_usable_context(contexts: list[ProviderContext]) -> bool:
    return any(context.status == "success" and bool(context.signals) for context in contexts)


def _with_run_id(review: DevReviewCreate, run_id: int) -> DevReviewCreate:
    return review.model_copy(update={"run_id": run_id})
