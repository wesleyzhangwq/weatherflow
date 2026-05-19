"""Build `ReflectionContext` from SQLite repos (no LLM)."""

from __future__ import annotations

from typing import Any

from app.memory import checkin_repo, dev_review_repo, profile_md, state_repo
from app.memory.schemas import ReflectionContext, ReflectionKind


def gather_reflection_context(
    kind: ReflectionKind,
    pattern_report: dict[str, Any],
) -> ReflectionContext:
    """Load check-ins, state trend, profile, and dev review evidence for reflection.

    ``pattern_report`` must be supplied by the orchestrator (single ``detect_patterns`` call).
    """
    window = 7 if kind == "daily" else 14
    latest_checkin = checkin_repo.latest()
    recent_checkins = checkin_repo.recent(limit=window)
    latest_state = state_repo.latest()
    recent_states = state_repo.trend(days=window)
    latest_dev_review = dev_review_repo.latest_review()
    return ReflectionContext(
        latest_checkin=latest_checkin,
        recent_checkins=recent_checkins,
        latest_state=latest_state,
        recent_states=recent_states,
        profile=profile_md.read_profile(max_chars=3000),
        latest_dev_review=(
            {
                "created_at": latest_dev_review.created_at,
                "window_days": latest_dev_review.window_days,
                "dev_weather": latest_dev_review.dev_weather,
                "summary": latest_dev_review.summary,
                "main_work_threads": latest_dev_review.main_work_threads,
                "rhythm_risks": latest_dev_review.rhythm_risks,
                "next_week_suggestion": latest_dev_review.next_week_suggestion,
            }
            if latest_dev_review
            else None
        ),
        pattern_report=pattern_report,
    )


__all__ = ["gather_reflection_context"]
