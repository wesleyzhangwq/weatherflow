import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class LoopStatus(StrEnum):
    SUCCEEDED = "succeeded"
    WAITING_APPROVAL = "waiting_approval"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class LoopOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    status: LoopStatus
    result_summary: str | None = None
    action_id: str | None = None
    approval_id: str | None = None
    error: str | None = None


class BoundedObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    output: dict[str, Any]
    truncated: bool = False
    original_chars: int

    @classmethod
    def from_output(cls, output: dict[str, Any], *, max_chars: int = 8000) -> "BoundedObservation":
        encoded = json.dumps(
            output,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(encoded) <= max_chars:
            return cls(output=output, original_chars=len(encoded))
        return cls(
            output={"preview": encoded[:max_chars]},
            truncated=True,
            original_chars=len(encoded),
        )
