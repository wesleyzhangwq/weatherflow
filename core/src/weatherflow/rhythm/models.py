from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from ulid import ULID


class AppCategory(StrEnum):
    DEVELOPMENT = "development"
    COMMUNICATION = "communication"
    RESEARCH = "research"
    PLANNING = "planning"
    CREATIVE = "creative"
    OTHER = "other"


class DimensionName(StrEnum):
    ENERGY = "energy"
    COGNITIVE_LOAD = "cognitive_load"
    FRAGMENTATION = "fragmentation"
    MOMENTUM = "momentum"
    FRICTION = "friction"
    RECOVERY_NEED = "recovery_need"


class Trend(StrEnum):
    RISING = "rising"
    STEADY = "steady"
    FALLING = "falling"


class Freshness(StrEnum):
    FRESH = "fresh"
    AGING = "aging"
    EXPIRED = "expired"


class CheckInSignal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["checkin"] = "checkin"
    text: str = Field(min_length=1, max_length=2000)
    observed_at: datetime


class CorrectionSignal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["correction"] = "correction"
    text: str = Field(min_length=1, max_length=2000)
    target: DimensionName | None = None
    observed_at: datetime


class ActivityMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["activity_metadata"] = "activity_metadata"
    observed_at: datetime
    window_start: datetime
    window_end: datetime
    active_seconds: int = Field(ge=0)
    idle_seconds: int = Field(ge=0)
    app_switch_count: int = Field(ge=0)
    category_seconds: dict[AppCategory, int]


class TaskBehaviorSignal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["task_behavior"] = "task_behavior"
    observed_at: datetime
    run_id: str = Field(min_length=1)
    outcome: Literal["succeeded", "failed", "needs_review"]
    duration_seconds: float = Field(ge=0)
    step_count: int = Field(ge=0)


RhythmSignal = Annotated[
    CheckInSignal | CorrectionSignal | ActivityMetadata | TaskBehaviorSignal,
    Field(discriminator="kind"),
]


class DimensionEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    trend: Trend
    supporting_event_ids: tuple[str, ...]
    contradicting_event_ids: tuple[str, ...]
    freshness: Freshness


class HumanStateSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    workspace_id: str
    observed_at: datetime
    window_start: datetime
    window_end: datetime
    dimensions: dict[DimensionName, DimensionEstimate]
    summary: str
    supporting_event_ids: tuple[str, ...]
    contradicting_event_ids: tuple[str, ...]
    freshness: Freshness
    valid_until: datetime
    estimator_version: str = "rhythm-v1"

    @model_validator(mode="after")
    def all_dimensions_are_present(self) -> "HumanStateSnapshot":
        if set(self.dimensions) != set(DimensionName):
            raise ValueError("all six rhythm dimensions are required")
        return self

    @classmethod
    def new(
        cls,
        *,
        workspace_id: str,
        observed_at: datetime,
        window_start: datetime,
        window_end: datetime,
        dimensions: dict[DimensionName, DimensionEstimate],
        summary: str,
        supporting_event_ids: tuple[str, ...],
        contradicting_event_ids: tuple[str, ...],
        valid_until: datetime,
        freshness: Freshness = Freshness.FRESH,
    ) -> "HumanStateSnapshot":
        return cls(
            id=str(ULID()),
            workspace_id=workspace_id,
            observed_at=observed_at,
            window_start=window_start,
            window_end=window_end,
            dimensions=dimensions,
            summary=summary,
            supporting_event_ids=supporting_event_ids,
            contradicting_event_ids=contradicting_event_ids,
            freshness=freshness,
            valid_until=valid_until,
        )


class WorkMode(StrEnum):
    SINGLE_THREAD = "single_thread"
    NORMAL = "normal"
    DIAGNOSTIC = "diagnostic"


class RhythmPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    interaction_budget: Literal["minimal", "normal", "generous"]
    response_density: Literal["compact", "normal", "detailed"]
    delegation_bias: Literal["favor", "neutral", "avoid"]
    scope_pressure: Literal["reduce", "hold"]
    work_mode: WorkMode
    proactivity: Literal["silent"] = "silent"
    reason_refs: tuple[str, ...]
    valid_until: datetime

    @classmethod
    def from_snapshot(cls, snapshot: HumanStateSnapshot) -> "RhythmPolicy":
        return cls(
            interaction_budget="normal",
            response_density="normal",
            delegation_bias="neutral",
            scope_pressure="hold",
            work_mode=WorkMode.NORMAL,
            reason_refs=snapshot.supporting_event_ids,
            valid_until=snapshot.valid_until,
        )


class WeatherScene(StrEnum):
    CLEAR = "clear"
    FAIR = "fair"
    FOG = "fog"
    STORM = "storm"
    STILL = "still"
    NIGHT = "night"
    MIXED = "mixed"


class WeatherPresentation(BaseModel):
    model_config = ConfigDict(frozen=True)

    scene: WeatherScene
    intensity: float = Field(ge=0, le=1)
    transition: Literal["steady", "building", "easing"]
    snapshot_id: str
    valid_until: datetime
    presentation_version: str = "weather-v1"


def expired_snapshot(workspace_id: str) -> HumanStateSnapshot:
    now = datetime.now(UTC)
    estimate = DimensionEstimate(
        value=0.5,
        confidence=0,
        trend=Trend.STEADY,
        supporting_event_ids=(),
        contradicting_event_ids=(),
        freshness=Freshness.EXPIRED,
    )
    return HumanStateSnapshot.new(
        workspace_id=workspace_id,
        observed_at=now,
        window_start=now - timedelta(hours=1),
        window_end=now,
        dimensions={name: estimate for name in DimensionName},
        summary="Insufficient current evidence",
        supporting_event_ids=(),
        contradicting_event_ids=(),
        valid_until=now,
        freshness=Freshness.EXPIRED,
    )
