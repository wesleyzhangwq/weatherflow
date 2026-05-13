"""Pydantic models that mirror the storage tables."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ----------------------------- Check-in -----------------------------
class CheckinIn(BaseModel):
    status: Optional[str] = Field(default=None, description="how you feel today")
    did_today: Optional[str] = Field(default=None, description="what you did today")
    stuck_on: Optional[str] = Field(default=None, description="what is stuck")
    anxiety: Optional[str] = Field(default=None, description="current most anxious thing")
    raw: Optional[str] = Field(default=None, description="any free-form journaling")
    session_id: str = Field(default="default", description="correlate short-term buffer + events")


class CheckinRecord(CheckinIn):
    id: int
    date: str
    created_at: str


# ----------------------------- Reflection -----------------------------
ReflectionKind = Literal["daily", "weekly"]
GroundingSourceType = Literal[
    "checkin",
    "state",
    "git",
    "notes",
    "workspace",
    "patterns",
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


# ----------------------------- Timeline -----------------------------
TimelineKind = Literal["milestone", "phase", "event"]


class TimelineEvent(BaseModel):
    id: Optional[int] = None
    ts: str
    kind: TimelineKind
    title: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


# ----------------------------- Semantic memory -----------------------------
class SemanticItem(BaseModel):
    key: str
    value: str
    confidence: float = 0.5
    last_updated: Optional[str] = None


# ----------------------------- Episodic -----------------------------
class EpisodicItem(BaseModel):
    id: int
    ts: str
    content: str
    source: str


# ----------------------------- Git activity -----------------------------
class GitActivityIn(BaseModel):
    repo: str
    commit_count: int = 0
    project_count: int = 0
    switch_score: float = 0.0
    window_days: int = 14


class GitActivityRecord(GitActivityIn):
    id: int
    ts: str


# ----------------------------- Notes activity -----------------------------
class NotesActivityIn(BaseModel):
    root: str
    file_count: int = 0
    new_file_count: int = 0
    edited_count: int = 0
    total_words: int = 0
    new_words: int = 0
    avg_words: float = 0.0
    top_topics: List[str] = Field(default_factory=list)
    window_days: int = 14


class NotesActivityRecord(NotesActivityIn):
    id: int
    ts: str


class SensorSweepIn(BaseModel):
    """Optional overrides; empty lists mean \"use server defaults from .env / home\"."""

    git_roots: List[str] = Field(default_factory=list)
    notes_roots: List[str] = Field(default_factory=list)
    workspace_roots: List[str] = Field(default_factory=list)
    window_days: int = 14
    dry_run: bool = False


# ----------------------------- Short-term events -----------------------------
class EventIn(BaseModel):
    type: str = Field(..., description="chat / action / reflection / state / sensor / ...")
    content: str
    tags: List[str] = Field(default_factory=list)
    session_id: str = "default"


class EventRecord(EventIn):
    id: str
    timestamp: str


# ----------------------------- Workspace activity -----------------------------
class WorkspaceActivityIn(BaseModel):
    root: str
    active_project_count: int = 0
    touched_paths: int = 0
    fragmentation_score: float = 0.0
    top_dirs: List[str] = Field(default_factory=list)
    window_days: int = 7


class WorkspaceActivityRecord(WorkspaceActivityIn):
    id: int
    ts: str


__all__ = [
    "CheckinIn",
    "CheckinRecord",
    "ReflectionKind",
    "GroundingSourceType",
    "GroundingSource",
    "ReflectionRecord",
    "WeatherLabel",
    "UserStateOut",
    "StateTrendPoint",
    "TimelineKind",
    "TimelineEvent",
    "SemanticItem",
    "EpisodicItem",
    "GitActivityIn",
    "GitActivityRecord",
    "NotesActivityIn",
    "NotesActivityRecord",
    "SensorSweepIn",
    "EventIn",
    "EventRecord",
    "WorkspaceActivityIn",
    "WorkspaceActivityRecord",
]
