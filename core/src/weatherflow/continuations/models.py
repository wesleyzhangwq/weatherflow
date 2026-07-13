import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_CONTINUATION_BYTES = 4_000_000


class ProviderContinuationUnavailableError(RuntimeError):
    """The exact provider history required to resume a Run is unavailable."""


class ProviderAssistantMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    model: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any]

    @model_validator(mode="after")
    def bounded_assistant_payload(self) -> "ProviderAssistantMessage":
        if self.payload.get("role") != "assistant":
            raise ValueError("provider continuation must be an assistant message")
        encoded = json.dumps(
            self.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if len(encoded) > MAX_CONTINUATION_BYTES:
            raise ValueError("provider continuation exceeds size limit")
        return self


class ProviderContinuation(ProviderAssistantMessage):
    run_id: str = Field(min_length=1, max_length=200)
    step_index: int = Field(ge=1)
    created_at: datetime
    expires_at: datetime

    @field_validator("created_at", "expires_at")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("continuation timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def expires_after_creation(self) -> "ProviderContinuation":
        if self.expires_at <= self.created_at:
            raise ValueError("continuation expiry must follow creation")
        return self
