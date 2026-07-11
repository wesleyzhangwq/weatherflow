from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from ulid import ULID


class EpisodicMemory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    workspace_id: str
    summary: str = Field(min_length=1, max_length=2_000)
    source_event_ids: tuple[str, ...] = Field(min_length=1, max_length=50)
    tags: tuple[str, ...] = Field(default=(), max_length=20)
    created_at: datetime

    @field_validator("source_event_ids")
    @classmethod
    def unique_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("source event IDs must be unique")
        return value

    @classmethod
    def new(
        cls,
        *,
        workspace_id: str,
        summary: str,
        source_event_ids: tuple[str, ...],
        tags: tuple[str, ...] = (),
    ) -> "EpisodicMemory":
        return cls(
            id=str(ULID()),
            workspace_id=workspace_id,
            summary=summary,
            source_event_ids=source_event_ids,
            tags=tags,
            created_at=datetime.now(UTC),
        )


class ProfileAssertionStatus(StrEnum):
    ACTIVE = "active"
    RETRACTED = "retracted"


class ProfileAssertion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    workspace_id: str
    claim: str = Field(min_length=1, max_length=2_000)
    confidence: float = Field(ge=0, le=1)
    status: ProfileAssertionStatus = ProfileAssertionStatus.ACTIVE
    evidence_event_ids: tuple[str, ...] = Field(min_length=1, max_length=50)
    origin: Literal["user", "agent", "derived"]
    version: int = Field(default=0, ge=0)
    created_at: datetime
    last_confirmed_at: datetime
    updated_at: datetime

    @field_validator("evidence_event_ids")
    @classmethod
    def unique_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("evidence event IDs must be unique")
        return value

    @classmethod
    def new(
        cls,
        *,
        workspace_id: str,
        claim: str,
        confidence: float,
        evidence_event_ids: tuple[str, ...],
        origin: Literal["user", "agent", "derived"],
    ) -> "ProfileAssertion":
        now = datetime.now(UTC)
        return cls(
            id=str(ULID()),
            workspace_id=workspace_id,
            claim=claim,
            confidence=confidence,
            evidence_event_ids=evidence_event_ids,
            origin=origin,
            created_at=now,
            last_confirmed_at=now,
            updated_at=now,
        )


class MemoryRecall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["episode", "profile_assertion"]
    entry_id: str
    text: str
    source_event_ids: tuple[str, ...]
    score: int = Field(ge=1)
