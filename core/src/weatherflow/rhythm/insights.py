from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from weatherflow.events import Event, EventLedger
from weatherflow.memory import ProfileAssertionRepository, ProfileAssertionStatus
from weatherflow.rhythm.models import AppCategory, TaskBehaviorSignal
from weatherflow.rhythm.service import CurrentRhythm, RhythmService


class RecentBehaviorInsight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: Literal["activity", "task"]
    observed_at: datetime
    active_minutes: float | None = Field(default=None, ge=0)
    idle_minutes: float | None = Field(default=None, ge=0)
    app_switch_count: int | None = Field(default=None, ge=0)
    dominant_category: AppCategory | None = None
    outcome: Literal["succeeded", "failed", "needs_review"] | None = None
    duration_minutes: float | None = Field(default=None, ge=0)
    step_count: int | None = Field(default=None, ge=0)


class ProfileInsight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    claim: str
    confidence: float = Field(ge=0, le=1)
    origin: Literal["user", "agent", "derived"]
    evidence_count: int = Field(ge=1)
    updated_at: datetime


class RhythmInsights(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    current: CurrentRhythm
    recent_behaviors: tuple[RecentBehaviorInsight, ...]
    profile: tuple[ProfileInsight, ...]


class RhythmInsightsService:
    """Build the privacy-safe read model used by the desktop status view."""

    def __init__(
        self,
        *,
        rhythm: RhythmService,
        ledger: EventLedger,
        profiles: ProfileAssertionRepository,
    ) -> None:
        self.rhythm = rhythm
        self.ledger = ledger
        self.profiles = profiles

    async def current(
        self,
        workspace_id: str,
        *,
        behavior_limit: int = 12,
        profile_limit: int = 8,
    ) -> RhythmInsights:
        if not 1 <= behavior_limit <= 50 or not 1 <= profile_limit <= 50:
            raise ValueError("insight limits must be between 1 and 50")
        current = await self.rhythm.current(workspace_id)
        events = await self.ledger.list_stream_recent("workspace", workspace_id, limit=1000)
        behaviors = tuple(
            insight for event in events if (insight := _behavior_insight(event)) is not None
        )[:behavior_limit]
        assertions = await self.profiles.list_workspace(workspace_id)
        profile = tuple(
            ProfileInsight(
                id=assertion.id,
                claim=assertion.claim,
                confidence=assertion.confidence,
                origin=assertion.origin,
                evidence_count=len(assertion.evidence_event_ids),
                updated_at=assertion.updated_at,
            )
            for assertion in sorted(
                (item for item in assertions if item.status is ProfileAssertionStatus.ACTIVE),
                key=lambda item: (item.updated_at, item.id),
                reverse=True,
            )[:profile_limit]
        )
        return RhythmInsights(
            current=current,
            recent_behaviors=behaviors,
            profile=profile,
        )


def _behavior_insight(event: Event) -> RecentBehaviorInsight | None:
    signal_payload = event.payload.get("signal")
    if not isinstance(signal_payload, dict):
        return None
    try:
        if event.type == "rhythm.signal.task_behavior":
            signal = TaskBehaviorSignal.model_validate(signal_payload)
            return RecentBehaviorInsight(
                id=event.id,
                kind="task",
                observed_at=signal.observed_at,
                outcome=signal.outcome,
                duration_minutes=round(signal.duration_seconds / 60, 1),
                step_count=signal.step_count,
            )
    except ValidationError:
        return None
    return None
