from __future__ import annotations

from datetime import datetime
from typing import Any

from weatherflow.activity.inference import (
    ActivityInferenceJob,
    ActivityInferenceJobStatus,
)
from weatherflow.activity.models import require_aware
from weatherflow.rhythm import HumanStateSnapshot
from weatherflow.storage import Database


class ActivityInferenceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def claim(
        self,
        *,
        scheduled_for: datetime,
        window_start: datetime,
        workspace_id: str,
        now: datetime,
    ) -> ActivityInferenceJob:
        candidate = ActivityInferenceJob.new(
            scheduled_for=scheduled_for,
            window_start=window_start,
            workspace_id=workspace_id,
            now=now,
        )
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT OR IGNORE INTO activity_inference_jobs(
                    id, scheduled_for, window_start, window_end, workspace_id,
                    status, config, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(candidate),
            )
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_inference_jobs WHERE scheduled_for = ?",
                    (candidate.scheduled_for.isoformat(),),
                )
            ).fetchone()
        if row is None:
            raise RuntimeError(candidate.id)
        return self._from_row(row)

    async def mark_executing(
        self,
        job_id: str,
        *,
        provider: str,
        model: str,
        base_url: str | None = None,
        configuration_version: int | None = None,
        event_ids: tuple[str, ...],
        chunk_count: int = 1,
        redaction_count: int,
        request_payload: str,
        now: datetime,
    ) -> ActivityInferenceJob:
        claimed = await self.try_mark_executing(
            job_id,
            provider=provider,
            model=model,
            base_url=base_url,
            configuration_version=configuration_version,
            event_ids=event_ids,
            chunk_count=chunk_count,
            redaction_count=redaction_count,
            request_payload=request_payload,
            now=now,
        )
        return claimed or await self._required(job_id)

    async def try_mark_executing(
        self,
        job_id: str,
        *,
        provider: str,
        model: str,
        base_url: str | None = None,
        configuration_version: int | None = None,
        event_ids: tuple[str, ...],
        chunk_count: int = 1,
        redaction_count: int,
        request_payload: str,
        now: datetime,
    ) -> ActivityInferenceJob | None:
        async with self.database.transaction() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_inference_jobs WHERE id = ?",
                    (job_id,),
                )
            ).fetchone()
            if row is None:
                raise LookupError(job_id)
            job = self._from_row(row)
            if job.status is not ActivityInferenceJobStatus.PENDING:
                return None
            updated = job.model_copy(
                update={
                    "status": ActivityInferenceJobStatus.EXECUTING,
                    "provider": provider,
                    "model": model,
                    "base_url": base_url,
                    "configuration_version": configuration_version,
                    "event_ids": event_ids,
                    "event_count": len(event_ids),
                    "chunk_count": chunk_count,
                    "redaction_count": redaction_count,
                    "request_payload": request_payload,
                    "updated_at": require_aware(now),
                }
            )
            await self._update_in(connection, updated)
            return updated

    async def recover_executing(self, *, now: datetime) -> list[ActivityInferenceJob]:
        observed = require_aware(now)
        async with self.database.transaction() as connection:
            rows = await (
                await connection.execute(
                    "SELECT config FROM activity_inference_jobs WHERE status = ?",
                    (ActivityInferenceJobStatus.EXECUTING.value,),
                )
            ).fetchall()
            recovered: list[ActivityInferenceJob] = []
            for row in rows:
                job = self._from_row(row).model_copy(
                    update={
                        "status": ActivityInferenceJobStatus.NEEDS_REVIEW,
                        "error_code": "delivery_uncertain_after_restart",
                        "updated_at": observed,
                    }
                )
                await self._update_in(connection, job)
                recovered.append(job)
        return recovered

    async def update_request_payload(
        self,
        job_id: str,
        *,
        request_payload: str,
        now: datetime,
    ) -> ActivityInferenceJob:
        job = await self._required(job_id)
        if job.status is not ActivityInferenceJobStatus.EXECUTING:
            raise ValueError("only an executing inference job can append request audit")
        updated = job.model_copy(
            update={
                "request_payload": request_payload,
                "updated_at": require_aware(now),
            }
        )
        await self._update(updated)
        return updated

    async def mark_completed(
        self,
        job_id: str,
        *,
        request_payload: str | None = None,
        response_payload: str,
        snapshot: HumanStateSnapshot,
        now: datetime,
    ) -> ActivityInferenceJob:
        job = await self._required(job_id)
        updated = job.model_copy(
            update={
                "status": ActivityInferenceJobStatus.COMPLETED,
                "request_payload": request_payload or job.request_payload,
                "response_payload": response_payload,
                "snapshot": snapshot,
                "error_code": None,
                "updated_at": require_aware(now),
            }
        )
        await self._update(updated)
        return updated

    async def mark_failed(
        self,
        job_id: str,
        *,
        error_code: str,
        now: datetime,
    ) -> ActivityInferenceJob:
        job = await self._required(job_id)
        updated = job.model_copy(
            update={
                "status": ActivityInferenceJobStatus.FAILED,
                "error_code": error_code,
                "updated_at": require_aware(now),
            }
        )
        await self._update(updated)
        return updated

    async def latest_completed(self) -> ActivityInferenceJob | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT config FROM activity_inference_jobs
                    WHERE status = ?
                    ORDER BY scheduled_for DESC, id DESC LIMIT 1
                    """,
                    (ActivityInferenceJobStatus.COMPLETED.value,),
                )
            ).fetchone()
        return self._from_row(row) if row else None

    async def list_history(self, *, limit: int = 100) -> list[ActivityInferenceJob]:
        if limit < 1 or limit > 1_000:
            raise ValueError("limit must be between 1 and 1000")
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT config FROM activity_inference_jobs
                    ORDER BY scheduled_for DESC, id DESC LIMIT ?
                    """,
                    (limit,),
                )
            ).fetchall()
        return [self._from_row(row) for row in rows]

    async def get_by_slot(self, scheduled_for: datetime) -> ActivityInferenceJob | None:
        slot = require_aware(scheduled_for)
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_inference_jobs WHERE scheduled_for = ?",
                    (slot.isoformat(),),
                )
            ).fetchone()
        return self._from_row(row) if row else None

    async def get(self, job_id: str) -> ActivityInferenceJob | None:
        try:
            return await self._required(job_id)
        except LookupError:
            return None

    async def delete_for_event_ids(self, event_ids: tuple[str, ...]) -> int:
        targets = set(event_ids)
        if not targets:
            return 0
        async with self.database.transaction() as connection:
            rows = await (
                await connection.execute("SELECT id, config FROM activity_inference_jobs")
            ).fetchall()
            deleted = 0
            for row in rows:
                job = self._from_row(row)
                if targets.intersection(job.event_ids):
                    cursor = await connection.execute(
                        "DELETE FROM activity_inference_jobs WHERE id = ?",
                        (job.id,),
                    )
                    deleted += cursor.rowcount
        return deleted

    async def _required(self, job_id: str) -> ActivityInferenceJob:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_inference_jobs WHERE id = ?",
                    (job_id,),
                )
            ).fetchone()
        if row is None:
            raise LookupError(job_id)
        return self._from_row(row)

    async def _update(self, job: ActivityInferenceJob) -> None:
        async with self.database.transaction() as connection:
            await self._update_in(connection, job)

    @staticmethod
    async def _update_in(connection, job: ActivityInferenceJob) -> None:
        cursor = await connection.execute(
            """
            UPDATE activity_inference_jobs
            SET status = ?, config = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                job.status.value,
                job.model_dump_json(),
                job.updated_at.isoformat(),
                job.id,
            ),
        )
        if cursor.rowcount != 1:
            raise LookupError(job.id)

    @staticmethod
    def _values(job: ActivityInferenceJob) -> tuple[object, ...]:
        return (
            job.id,
            job.scheduled_for.isoformat(),
            job.window_start.isoformat(),
            job.window_end.isoformat(),
            job.workspace_id,
            job.status.value,
            job.model_dump_json(),
            job.created_at.isoformat(),
            job.updated_at.isoformat(),
        )

    @staticmethod
    def _from_row(row: Any) -> ActivityInferenceJob:
        return ActivityInferenceJob.model_validate_json(row["config"])
