from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from weatherflow.runtime.models import AgentMessage


class RunCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    version: int = Field(ge=0)
    step_index: int = Field(ge=0)
    transcript: tuple[AgentMessage, ...]
    state: dict[str, Any]
    pending_action_id: str | None = None
    updated_at: datetime

    @classmethod
    def new(
        cls,
        *,
        run_id: str,
        transcript: tuple[AgentMessage, ...] = (),
        state: dict[str, Any] | None = None,
    ) -> "RunCheckpoint":
        return cls(
            run_id=run_id,
            version=0,
            step_index=0,
            transcript=transcript,
            state=state or {},
            updated_at=datetime.now(UTC),
        )
