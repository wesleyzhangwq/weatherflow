"""Build `ReflectionContext` from SQLite repos (no LLM)."""

from __future__ import annotations

from typing import Any

from app.memory import checkin_repo, hypothesis_repo, semantic, state_repo
from app.memory.schemas import ReflectionContext, ReflectionKind


def gather_reflection_context(
    kind: ReflectionKind,
    pattern_report: dict[str, Any],
) -> ReflectionContext:
    """Load check-ins, state trend, semantic memory, and hypotheses for reflection.

    ``pattern_report`` must be supplied by the orchestrator (single ``detect_patterns`` call).
    """
    window = 7 if kind == "daily" else 14
    latest_checkin = checkin_repo.latest()
    recent_checkins = checkin_repo.recent(limit=window)
    latest_state = state_repo.latest()
    recent_states = state_repo.trend(days=window)
    recent_semantic = semantic.all(limit=6)
    active_hypotheses = hypothesis_repo.active(limit=8)
    pending_hypotheses = hypothesis_repo.pending(limit=8)
    return ReflectionContext(
        latest_checkin=latest_checkin,
        recent_checkins=recent_checkins,
        latest_state=latest_state,
        recent_states=recent_states,
        recent_semantic=recent_semantic,
        active_hypotheses=active_hypotheses,
        pending_hypotheses=pending_hypotheses,
        pattern_report=pattern_report,
    )


__all__ = ["gather_reflection_context"]
