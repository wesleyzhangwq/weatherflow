"""Pydantic models that mirror the storage tables."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ----------------------------- Check-in -----------------------------
class CheckinIn(BaseModel):
    status: Optional[str] = Field(default=None, description="how you feel today")
    did_today: Optional[str] = Field(default=None, description="what you did today")
    stuck_on: Optional[str] = Field(default=None, description="what is stuck")
    anxiety: Optional[str] = Field(default=None, description="current most anxious thing")
    raw: Optional[str] = Field(default=None, description="any free-form journaling")
    session_id: str = Field(default="default", description="correlate feedback events")


class CheckinRecord(CheckinIn):
    id: int
    date: str
    created_at: str


# ----------------------------- Reflection -----------------------------
ReflectionKind = Literal["daily", "weekly"]
GroundingSourceType = Literal[
    "checkin",
    "state",
    "patterns",
    "dev_review",
    "memory",
]


class GroundingSource(BaseModel):
    type: GroundingSourceType
    label: str
    summary: str


class ReflectionRecord(BaseModel):
    id: int
    date: str
    kind: ReflectionKind
    content: str
    insights: Optional[dict] = None
    created_at: str


# ----------------------------- State -----------------------------
WeatherLabel = Literal["Momentum", "Confusion", "Burnout", "Overload", "Recovery"]


class UserStateOut(BaseModel):
    focus: int
    stress: int
    burnout: int
    momentum: int
    confidence: int
    motivation: int
    weather_label: WeatherLabel
    rationale: Optional[str] = None
    ts: Optional[str] = None


class StateTrendPoint(BaseModel):
    ts: str
    focus: int
    stress: int
    burnout: int
    momentum: int
    confidence: int
    motivation: int
    weather_label: WeatherLabel


class ReflectionContext(BaseModel):
    """Structured snapshot for `ReflectionAgent` — assembled by the orchestrator."""

    latest_checkin: Optional[CheckinRecord] = None
    recent_checkins: List[CheckinRecord] = Field(default_factory=list)
    latest_state: Optional[UserStateOut] = None
    recent_states: List[StateTrendPoint] = Field(default_factory=list)
    profile: str = ""
    latest_dev_review: Optional[Dict[str, Any]] = None
    pattern_report: Dict[str, Any] = Field(default_factory=dict)


# ----------------------------- Short-term events -----------------------------
class EventIn(BaseModel):
    type: str = Field(..., description="suggestion_feedback / memory_feedback / ...")
    content: str
    tags: List[str] = Field(default_factory=list)
    session_id: str = "default"


class EventRecord(EventIn):
    id: str
    timestamp: str


# ----------------------------- Dev review agent runs -----------------------------
DevWeather = Literal["Deep Work", "Shipping", "Collaboration Heavy", "Fragmented", "Blocked"]
RunStatus = Literal["running", "success", "partial", "failed"]
ProviderStatus = Literal["success", "partial", "failed", "skipped"]
DevReviewProviderReadinessStatus = Literal["ready", "needs_config"]


class DevReviewProviderReadiness(BaseModel):
    name: Literal["github", "google_calendar"]
    label: str
    status: DevReviewProviderReadinessStatus
    required_env: str
    used_for: str
    blocking: bool = False


class ProviderContext(BaseModel):
    source: str
    status: ProviderStatus
    window_days: int = 7
    signals: Dict[str, Any] = Field(default_factory=dict)
    coverage: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class AgentRunStep(BaseModel):
    name: str
    status: ProviderStatus
    summary: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentRunCreate(BaseModel):
    run_type: Literal["dev_review"] = "dev_review"
    input: Dict[str, Any] = Field(default_factory=dict)


class AgentRunRecord(BaseModel):
    id: int
    run_type: Literal["dev_review"]
    status: RunStatus
    started_at: str
    finished_at: Optional[str] = None
    input: Dict[str, Any] = Field(default_factory=dict)
    steps: List[AgentRunStep] = Field(default_factory=list)
    error: Optional[str] = None


class DevReviewCreate(BaseModel):
    run_id: int
    window_days: int = 7
    summary: str
    dev_weather: DevWeather
    main_work_threads: List[str] = Field(default_factory=list)
    shipping_progress: List[str] = Field(default_factory=list)
    collaboration_load: List[str] = Field(default_factory=list)
    meeting_load: List[str] = Field(default_factory=list)
    rhythm_risks: List[str] = Field(default_factory=list)
    next_week_suggestion: str
    source_coverage: Dict[str, Any] = Field(default_factory=dict)


class DevReviewRecord(DevReviewCreate):
    id: int
    created_at: str
    run: AgentRunRecord


class DevReviewRunRequest(BaseModel):
    window_days: int = Field(default=7, ge=1, le=31)
    providers: List[Literal["github", "google_calendar"]] = Field(
        default_factory=lambda: ["github", "google_calendar"]
    )


__all__ = [
    "CheckinIn",
    "CheckinRecord",
    "ReflectionContext",
    "ReflectionKind",
    "GroundingSourceType",
    "GroundingSource",
    "ReflectionRecord",
    "WeatherLabel",
    "UserStateOut",
    "StateTrendPoint",
    "EventIn",
    "EventRecord",
    "DevReviewProviderReadinessStatus",
    "DevReviewProviderReadiness",
    "DevWeather",
    "RunStatus",
    "ProviderStatus",
    "ProviderContext",
    "AgentRunStep",
    "AgentRunCreate",
    "AgentRunRecord",
    "DevReviewCreate",
    "DevReviewRecord",
    "DevReviewRunRequest",
]
