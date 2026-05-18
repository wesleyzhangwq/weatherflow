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
    DevReviewProviderReadiness,
    DevReviewRecord,
    DevReviewRunRequest,
    ProviderContext,
    ProviderStatus,
)
from app.routers._deps import get_llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dev-review", tags=["dev-review"])

_NO_PROVIDER_MESSAGE = "Configure at least one provider: GitHub or Google Calendar."


@router.get("/providers", response_model=list[DevReviewProviderReadiness])
def dev_review_providers() -> list[DevReviewProviderReadiness]:
    settings = get_settings()
    return [
        DevReviewProviderReadiness(
            name="github",
            label="GitHub",
            status="ready" if settings.github_token.strip() else "needs_config",
            required_env="GITHUB_TOKEN",
            used_for="PRs, issues, reviews, repository activity",
            blocking=False,
        ),
        DevReviewProviderReadiness(
            name="google_calendar",
            label="Google Calendar",
            status=(
                "ready"
                if settings.google_calendar_access_token.strip()
                else "needs_config"
            ),
            required_env="GOOGLE_CALENDAR_ACCESS_TOKEN",
            used_for="meeting load, focus windows, calendar event titles",
            blocking=False,
        ),
    ]


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
            reason = "GitHub access is not configured."
            contexts.append(
                _unavailable_provider_context(
                    source="github",
                    status="skipped",
                    window_days=payload.window_days,
                    reason=reason,
                )
            )
            tracker.step("github", "skipped", reason)
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
                reason = "GitHub provider failed."
                contexts.append(
                    _unavailable_provider_context(
                        source="github",
                        status="failed",
                        window_days=payload.window_days,
                        reason=reason,
                    )
                )
                tracker.step("github", "failed", reason)

    if "google_calendar" in payload.providers:
        if not settings.google_calendar_access_token.strip():
            reason = "Google Calendar access is not configured."
            contexts.append(
                _unavailable_provider_context(
                    source="google_calendar",
                    status="skipped",
                    window_days=payload.window_days,
                    reason=reason,
                )
            )
            tracker.step("google_calendar", "skipped", reason)
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
                reason = "Google Calendar provider failed."
                contexts.append(
                    _unavailable_provider_context(
                        source="google_calendar",
                        status="failed",
                        window_days=payload.window_days,
                        reason=reason,
                    )
                )
                tracker.step("google_calendar", "failed", reason)

    if not _has_usable_context(contexts):
        tracker.fail(_NO_PROVIDER_MESSAGE)
        raise HTTPException(status_code=400, detail=_NO_PROVIDER_MESSAGE)

    try:
        review = await DevReviewAgent(get_llm(request)).synthesize(
            payload.window_days,
            contexts,
        )
        review_id = dev_review_repo.create_review(_with_run_id(review, run_id))
        tracker.finish()
        persisted = dev_review_repo.get_review(review_id)
        if persisted is None:
            raise RuntimeError("Dev review was not persisted.")
        return persisted
    except Exception as exc:
        logger.exception("Dev review synthesis or persistence failed.")
        try:
            tracker.fail("Dev review synthesis or persistence failed.")
        except Exception:
            logger.exception("Failed to mark dev review run as failed.")
        raise HTTPException(
            status_code=500,
            detail="Dev review synthesis or persistence failed.",
        ) from exc


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


def _unavailable_provider_context(
    *,
    source: str,
    status: ProviderStatus,
    window_days: int,
    reason: str,
) -> ProviderContext:
    return ProviderContext(
        source=source,
        status=status,
        window_days=window_days,
        signals={},
        coverage={"reason": reason},
        warnings=[reason],
    )


def _with_run_id(review: DevReviewCreate, run_id: int) -> DevReviewCreate:
    return review.model_copy(update={"run_id": run_id})
