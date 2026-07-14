from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from weatherflow.automations.models import (
    Automation,
    AutomationRunLink,
    AutomationStatus,
    ScheduleSpec,
)
from weatherflow.automations.repository import (
    AutomationNotFoundError,
    AutomationRepository,
    AutomationVersionConflict,
)


class RunSubmitter(Protocol):
    async def __call__(
        self,
        *,
        user_intent: str,
        client_request_id: str,
        workspace_id: str,
    ) -> Any: ...


class AutomationService:
    def __init__(
        self,
        *,
        repository: AutomationRepository,
        submit_run: RunSubmitter,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.submit_run = submit_run
        self.now = now or (lambda: datetime.now(UTC))

    async def create(
        self,
        *,
        workspace_id: str,
        name: str,
        prompt: str,
        schedule: ScheduleSpec,
    ) -> Automation:
        automation = Automation.new(
            workspace_id=workspace_id,
            name=name,
            prompt=prompt,
            schedule=schedule,
            now=self.now(),
        )
        await self.repository.create(automation)
        return automation

    async def get(self, automation_id: str) -> Automation | None:
        return await self.repository.get(automation_id)

    async def list(
        self,
        workspace_id: str,
        *,
        status: AutomationStatus | None = None,
    ) -> list[Automation]:
        return await self.repository.list(workspace_id, status=status)

    async def update(
        self,
        automation_id: str,
        *,
        expected_version: int,
        name: str | None = None,
        prompt: str | None = None,
        schedule: ScheduleSpec | None = None,
    ) -> Automation:
        current = await self._required(automation_id)
        if current.version != expected_version:
            raise AutomationVersionConflict(automation_id)
        observed = self.now()
        updated = Automation.model_validate(
            {
                **current.model_dump(),
                "name": name if name is not None else current.name,
                "prompt": prompt if prompt is not None else current.prompt,
                "schedule": schedule if schedule is not None else current.schedule,
                "next_run_at": (
                    schedule.next_after(observed - timedelta(microseconds=1))
                    if schedule is not None
                    else current.next_run_at
                ),
                "version": current.version + 1,
                "updated_at": observed,
            }
        )
        await self.repository.update(updated, expected_version=expected_version)
        return updated

    async def pause(self, automation_id: str, *, expected_version: int) -> Automation:
        return await self._set_status(
            automation_id,
            expected_version=expected_version,
            status=AutomationStatus.PAUSED,
        )

    async def resume(self, automation_id: str, *, expected_version: int) -> Automation:
        return await self._set_status(
            automation_id,
            expected_version=expected_version,
            status=AutomationStatus.ENABLED,
        )

    async def delete(self, automation_id: str, *, expected_version: int) -> None:
        current = await self._required(automation_id)
        if current.version != expected_version:
            raise AutomationVersionConflict(automation_id)
        await self.repository.delete(automation_id, expected_version=expected_version)

    async def history(
        self,
        automation_id: str,
        *,
        limit: int = 100,
    ) -> list[AutomationRunLink]:
        return await self.repository.list_history(automation_id, limit=limit)

    async def run_now(self, automation_id: str) -> AutomationRunLink:
        link = await self.repository.claim_manual(automation_id, now=self.now())
        return await self._submit(link)

    async def recover_pending(self) -> list[AutomationRunLink]:
        results: list[AutomationRunLink] = []
        for link in await self.repository.list_pending():
            results.append(await self._submit(link))
        return results

    async def tick(self) -> list[AutomationRunLink]:
        observed = self.now()
        results = await self.recover_pending()
        for automation in await self.repository.list_due(observed):
            link = await self.repository.claim_scheduled(automation.id, now=observed)
            if link is not None:
                results.append(await self._submit(link))
        return results

    async def _set_status(
        self,
        automation_id: str,
        *,
        expected_version: int,
        status: AutomationStatus,
    ) -> Automation:
        current = await self._required(automation_id)
        if current.version != expected_version:
            raise AutomationVersionConflict(automation_id)
        observed = self.now()
        updated = Automation.model_validate(
            {
                **current.model_dump(),
                "status": status,
                "version": current.version + 1,
                "updated_at": observed,
            }
        )
        await self.repository.update(updated, expected_version=expected_version)
        return updated

    async def _submit(self, link: AutomationRunLink) -> AutomationRunLink:
        automation = await self._required(link.automation_id)
        try:
            result = await self.submit_run(
                user_intent=automation.prompt,
                client_request_id=link.client_request_id,
                workspace_id=automation.workspace_id,
            )
            run_id = self._run_id(result)
        except Exception:
            return await self.repository.mark_failed(
                link.id,
                error_code="submission_failed",
                now=self.now(),
            )
        return await self.repository.mark_submitted(link.id, run_id=run_id, now=self.now())

    async def _required(self, automation_id: str) -> Automation:
        automation = await self.repository.get(automation_id)
        if automation is None:
            raise AutomationNotFoundError(automation_id)
        return automation

    @staticmethod
    def _run_id(result: Any) -> str:
        candidate = result[0] if isinstance(result, tuple) and result else result
        if isinstance(candidate, str) and candidate:
            return candidate
        run_id = getattr(candidate, "id", None)
        if isinstance(run_id, str) and run_id:
            return run_id
        raise TypeError("submit_run must return a Run, run id, or tuple beginning with a Run")


class AutomationScheduler:
    def __init__(
        self,
        *,
        service: AutomationService,
        interval_seconds: float = 30.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.service = service
        self.interval_seconds = interval_seconds
        self.sleep = sleep
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(self._run(), name="weatherflow-automations")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _run(self) -> None:
        while True:
            try:
                await self.service.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # One malformed or unavailable submission must not kill future schedules.
                pass
            await self.sleep(self.interval_seconds)
