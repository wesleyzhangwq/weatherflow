from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID


class Actor(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class Sensitivity(StrEnum):
    NORMAL = "normal"
    PRIVATE = "private"
    SECRET_REF = "secret_ref"


class RetentionClass(StrEnum):
    AUDIT = "audit"
    SIGNAL_RAW = "signal_raw"
    SIGNAL_AGGREGATE = "signal_aggregate"


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    type: str = Field(min_length=1)
    recorded_at: datetime
    actor: Actor
    stream_kind: str = Field(min_length=1)
    stream_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    causation_id: str | None = None
    payload: dict[str, Any]
    sensitivity: Sensitivity = Sensitivity.NORMAL
    retention_class: RetentionClass = RetentionClass.AUDIT

    @classmethod
    def new(
        cls,
        *,
        type: str,
        actor: Actor,
        stream_kind: str,
        stream_id: str,
        correlation_id: str,
        payload: dict[str, Any],
        causation_id: str | None = None,
        sensitivity: Sensitivity = Sensitivity.NORMAL,
        retention_class: RetentionClass = RetentionClass.AUDIT,
    ) -> "Event":
        return cls(
            id=str(ULID()),
            type=type,
            recorded_at=datetime.now(UTC),
            actor=actor,
            stream_kind=stream_kind,
            stream_id=stream_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=payload,
            sensitivity=sensitivity,
            retention_class=retention_class,
        )
