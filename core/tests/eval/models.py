from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TrajectoryCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    passed: bool
    evidence: dict[str, Any] = Field(default_factory=dict)


class TrajectoryReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    passed: bool
    checks: tuple[TrajectoryCheck, ...]
    metrics: dict[str, int | float]

    def metric(self, name: str) -> int | float:
        return self.metrics[name]
