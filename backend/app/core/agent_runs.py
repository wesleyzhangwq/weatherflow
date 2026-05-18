"""Lifecycle helpers for fixed-purpose agent runs."""

from __future__ import annotations

from typing import Any

from app.memory import dev_review_repo
from app.memory.schemas import AgentRunRecord, AgentRunStep, ProviderStatus


class AgentRunTracker:
    """Track provider steps and finish a fixed-purpose agent run."""

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        self._saw_non_success_step = False

    def step(
        self,
        name: str,
        status: ProviderStatus,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AgentRunStep:
        if status != "success":
            self._saw_non_success_step = True

        step = AgentRunStep(
            name=name,
            status=status,
            summary=summary,
            metadata=metadata or {},
        )
        dev_review_repo.append_step(self.run_id, step)
        return step

    def finish(self) -> AgentRunRecord:
        status = "partial" if self._saw_non_success_step else "success"
        return dev_review_repo.finish_run(self.run_id, status=status)

    def fail(self, error: str) -> AgentRunRecord:
        return dev_review_repo.finish_run(self.run_id, status="failed", error=error)


__all__ = ["AgentRunTracker"]
