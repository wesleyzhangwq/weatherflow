from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from ulid import ULID


class ActivitySource(StrEnum):
    MACOS_WINDOW = "macos_window"
    BROWSER_TAB = "browser_tab"
    IDLE = "idle"


class IdleState(StrEnum):
    ACTIVE = "active"
    IDLE = "idle"
    UNKNOWN = "unknown"


def require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


class ActivityHeartbeat(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: ActivitySource
    device_id: str = Field(min_length=1, max_length=200)
    source_instance: str = Field(min_length=1, max_length=200)
    source_event_id: str = Field(min_length=1, max_length=300)
    observed_at: datetime
    pulsetime_seconds: float = Field(gt=0, le=600)
    app_name: str | None = Field(default=None, max_length=500)
    bundle_id: str | None = Field(default=None, max_length=500)
    window_title: str | None = Field(default=None, max_length=4_000)
    browser_name: str | None = Field(default=None, max_length=200)
    browser_window_id: str | None = Field(default=None, max_length=200)
    browser_tab_id: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=16_000)
    domain: str | None = Field(default=None, max_length=500)
    tab_title: str | None = Field(default=None, max_length=4_000)
    audible: bool | None = None
    incognito: bool | None = None
    focused: bool | None = None
    idle_state: IdleState = IdleState.UNKNOWN
    category: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("observed_at")
    @classmethod
    def aware_observed_at(cls, value: datetime) -> datetime:
        return require_aware(value)

    @model_validator(mode="after")
    def fields_match_source(self) -> ActivityHeartbeat:
        if self.source is ActivitySource.MACOS_WINDOW:
            if not self.app_name or not self.bundle_id:
                raise ValueError("macOS window activity requires app_name and bundle_id")
        elif self.source is ActivitySource.BROWSER_TAB:
            required = (
                self.browser_name,
                self.browser_window_id,
                self.browser_tab_id,
                self.url,
                self.tab_title,
            )
            if not all(required):
                raise ValueError("browser activity requires browser, window, tab, URL, and title")
        elif self.idle_state is IdleState.UNKNOWN:
            raise ValueError("idle activity requires a known idle_state")
        return self

    def state_payload(self) -> dict[str, Any]:
        fields = (
            "source",
            "app_name",
            "bundle_id",
            "window_title",
            "browser_name",
            "browser_window_id",
            "browser_tab_id",
            "url",
            "domain",
            "tab_title",
            "audible",
            "incognito",
            "focused",
            "idle_state",
            "category",
        )
        return self.model_dump(mode="json", include=set(fields))

    def state_hash(self) -> str:
        encoded = json.dumps(
            self.state_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


class ActivityInterval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    source: ActivitySource
    device_id: str
    source_instance: str
    source_event_id: str
    started_at: datetime
    ended_at: datetime
    observed_at: datetime
    duration_seconds: float = Field(ge=0)
    app_name: str | None = None
    bundle_id: str | None = None
    window_title: str | None = None
    browser_name: str | None = None
    browser_window_id: str | None = None
    browser_tab_id: str | None = None
    url: str | None = None
    domain: str | None = None
    tab_title: str | None = None
    audible: bool | None = None
    incognito: bool | None = None
    focused: bool | None = None
    idle_state: IdleState
    category: str | None = None
    state_hash: str
    created_at: datetime
    updated_at: datetime

    @field_validator("started_at", "ended_at", "observed_at", "created_at", "updated_at")
    @classmethod
    def aware_timestamps(cls, value: datetime) -> datetime:
        return require_aware(value)

    @model_validator(mode="after")
    def valid_interval(self) -> ActivityInterval:
        if self.ended_at < self.started_at:
            raise ValueError("activity interval cannot end before it starts")
        expected = (self.ended_at - self.started_at).total_seconds()
        if abs(expected - self.duration_seconds) > 0.001:
            raise ValueError("duration_seconds must match the interval")
        return self

    @classmethod
    def from_heartbeat(cls, heartbeat: ActivityHeartbeat) -> ActivityInterval:
        observed = heartbeat.observed_at
        return cls(
            id=str(ULID()),
            source=heartbeat.source,
            device_id=heartbeat.device_id,
            source_instance=heartbeat.source_instance,
            source_event_id=heartbeat.source_event_id,
            started_at=observed,
            ended_at=observed,
            observed_at=observed,
            duration_seconds=0,
            app_name=heartbeat.app_name,
            bundle_id=heartbeat.bundle_id,
            window_title=heartbeat.window_title,
            browser_name=heartbeat.browser_name,
            browser_window_id=heartbeat.browser_window_id,
            browser_tab_id=heartbeat.browser_tab_id,
            url=heartbeat.url,
            domain=heartbeat.domain,
            tab_title=heartbeat.tab_title,
            audible=heartbeat.audible,
            incognito=heartbeat.incognito,
            focused=heartbeat.focused,
            idle_state=heartbeat.idle_state,
            category=heartbeat.category,
            state_hash=heartbeat.state_hash(),
            created_at=observed,
            updated_at=observed,
        )


class ActivityPreferences(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    collection_enabled: bool = False
    macos_enabled: bool = False
    browser_enabled: bool = False
    incognito_enabled: bool = False
    remote_inference_enabled: bool = False
    model_workspace_id: str | None = Field(default=None, min_length=1)
    retention_days: Literal[30, 90, 365] | None = None
    version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def remote_inference_has_model_workspace(self) -> ActivityPreferences:
        if self.remote_inference_enabled and not self.model_workspace_id:
            raise ValueError("remote inference requires a model workspace")
        return self


class ActivityRankItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    seconds: float = Field(ge=0)


class ActivitySummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    window_start: datetime
    window_end: datetime
    screen_seconds: float = Field(ge=0)
    browser_seconds: float = Field(ge=0)
    idle_seconds: float = Field(ge=0)
    current_streak_seconds: float = Field(ge=0)
    app_switch_count: int = Field(ge=0)
    tab_switch_count: int = Field(ge=0)
    category_seconds: dict[str, float]
    top_apps: tuple[ActivityRankItem, ...]
    top_domains: tuple[ActivityRankItem, ...]

    @field_validator("window_start", "window_end")
    @classmethod
    def aware_window(cls, value: datetime) -> datetime:
        return require_aware(value)

    @model_validator(mode="after")
    def valid_window(self) -> ActivitySummary:
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        return self
