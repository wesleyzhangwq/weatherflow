from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from weatherflow.activity.models import (
    ActivitySourceState,
    ActivitySummaryAttempt,
    ActivitySummaryDependency,
    ActivitySummaryRevision,
    ActivitySummarySettings,
    ActivitySummaryTask,
    ActivityTrendPoint,
    CategoryRuleVersion,
    SummaryAttemptStatus,
    SummaryFinality,
    SummaryTaskStatus,
    SummaryTaskType,
    canonical_digest,
    require_aware,
)
from weatherflow.activity.windows import FINAL_GRACE
from weatherflow.models.errors import ModelResponseFailureStage
from weatherflow.storage import Database

_EXPLICIT_REGENERATION_ERROR_CODES = frozenset(
    {
        "activity_model_invalid_response",
        "activity_model_output_rejected",
    }
)


class StaleActivitySummaryAttempt(RuntimeError):
    pass


class ActivitySummarySettingsVersionConflict(RuntimeError):
    pass


class ActivityRepository:
    """Persistence boundary for WeatherFlow-owned derived activity records."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def ensure_summary_settings(
        self,
        settings: ActivitySummarySettings,
    ) -> ActivitySummarySettings:
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT OR IGNORE INTO activity_summary_settings(
                    singleton_id, version, config, updated_at
                ) VALUES (1, ?, ?, ?)
                """,
                (
                    settings.version,
                    settings.model_dump_json(),
                    settings.updated_at.isoformat(),
                ),
            )
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_summary_settings WHERE singleton_id = 1"
                )
            ).fetchone()
        if row is None:
            raise RuntimeError("activity summary settings were not created")
        return ActivitySummarySettings.model_validate_json(row["config"])

    async def summary_settings(self) -> ActivitySummarySettings | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_summary_settings WHERE singleton_id = 1"
                )
            ).fetchone()
        return ActivitySummarySettings.model_validate_json(row["config"]) if row else None

    async def save_summary_settings(
        self,
        settings: ActivitySummarySettings,
        *,
        expected_version: int,
        now: datetime,
    ) -> ActivitySummarySettings:
        observed = require_aware(now)
        async with self.database.transaction() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_summary_settings WHERE singleton_id = 1"
                )
            ).fetchone()
            if row is None:
                raise LookupError("activity_summary_settings")
            current = ActivitySummarySettings.model_validate_json(row["config"])
            if current.version != expected_version:
                raise ActivitySummarySettingsVersionConflict(str(expected_version))
            updated = settings.model_copy(
                update={"version": current.version + 1, "updated_at": observed}
            )
            cursor = await connection.execute(
                """
                UPDATE activity_summary_settings
                SET version = ?, config = ?, updated_at = ?
                WHERE singleton_id = 1 AND version = ?
                """,
                (
                    updated.version,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    current.version,
                ),
            )
            if cursor.rowcount != 1:
                raise ActivitySummarySettingsVersionConflict(str(expected_version))
            selection_changed = any(
                getattr(current, field) != getattr(updated, field)
                for field in (
                    "model_workspace_id",
                    "provider",
                    "model",
                    "model_configuration_version",
                    "prompt_version",
                )
            )
            if selection_changed:
                rows = await (
                    await connection.execute(
                        """
                        SELECT config FROM activity_summary_tasks
                        WHERE status = ?
                        ORDER BY window_end, task_type, id
                        """,
                        (SummaryTaskStatus.COMPLETED.value,),
                    )
                ).fetchall()
                for task_row in rows:
                    task = self._task_from_row(task_row)
                    requeued = task.model_copy(
                        update={
                            "status": SummaryTaskStatus.NEEDS_RETRY,
                            "next_retry_at": observed,
                            "lease_owner": None,
                            "lease_expires_at": None,
                            "finality": None,
                            "completed_at": None,
                            "error_code": None,
                            "regeneration_reason": "summary_settings_changed",
                            "updated_at": observed,
                        }
                    )
                    await self._update_task_in(connection, requeued)
        return updated

    async def save_source_state(
        self,
        state: ActivitySourceState,
        *,
        preserve_history_cutoff: bool = True,
    ) -> ActivitySourceState:
        async with self.database.transaction() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_source_state WHERE singleton_id = 1"
                )
            ).fetchone()
            existing = (
                ActivitySourceState.model_validate_json(row["config"]) if row is not None else None
            )
            merged = self._merge_source_state(
                state,
                existing=existing,
                preserve_history_cutoff=preserve_history_cutoff,
            )
            await self._save_source_state_in(connection, merged)
        return merged

    async def source_state(self) -> ActivitySourceState | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_source_state WHERE singleton_id = 1"
                )
            ).fetchone()
        return ActivitySourceState.model_validate_json(row["config"]) if row else None

    async def save_category_rule_version(
        self,
        version: CategoryRuleVersion,
        *,
        now: datetime,
    ) -> CategoryRuleVersion:
        observed = require_aware(now)
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT OR IGNORE INTO activity_category_rule_versions(
                    id, canonical_json, rule_count, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    version.id,
                    version.canonical_json,
                    version.rule_count,
                    observed.isoformat(),
                ),
            )
        return version

    async def category_rule_version(self, version_id: str) -> CategoryRuleVersion | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT id, canonical_json, rule_count
                    FROM activity_category_rule_versions
                    WHERE id = ?
                    """,
                    (version_id,),
                )
            ).fetchone()
        return (
            CategoryRuleVersion(
                id=row["id"],
                canonical_json=row["canonical_json"],
                rule_count=row["rule_count"],
            )
            if row
            else None
        )

    async def ensure_tasks(self, tasks: list[ActivitySummaryTask]) -> int:
        inserted = 0
        async with self.database.transaction() as connection:
            state_row = await (
                await connection.execute(
                    "SELECT config FROM activity_source_state WHERE singleton_id = 1"
                )
            ).fetchone()
            cutoff = (
                ActivitySourceState.model_validate_json(state_row["config"]).history_cutoff
                if state_row is not None
                else None
            )
            for task in tasks:
                if cutoff is not None and task.window_start < cutoff:
                    continue
                cursor = await connection.execute(
                    """
                    INSERT OR IGNORE INTO activity_summary_tasks(
                        id, task_type, window_start, window_end, timezone,
                        boundary_policy_version, status, finality, attempt_count,
                        not_before, next_retry_at, lease_owner, lease_expires_at,
                        current_revision, category_rule_version, source_watermark,
                        config, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._task_values(task),
                )
                inserted += max(0, cursor.rowcount)
        return inserted

    async def ensure_dependencies(
        self,
        dependencies: list[ActivitySummaryDependency],
    ) -> int:
        inserted = 0
        async with self.database.transaction() as connection:
            for dependency in dependencies:
                cursor = await connection.execute(
                    """
                    INSERT OR IGNORE INTO activity_summary_dependencies(
                        parent_task_id, child_task_id
                    ) VALUES (?, ?)
                    """,
                    (dependency.parent_task_id, dependency.child_task_id),
                )
                inserted += max(0, cursor.rowcount)
        return inserted

    async def dependencies_for(self, task_id: str) -> list[ActivitySummaryDependency]:
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT parent_task_id, child_task_id
                    FROM activity_summary_dependencies
                    WHERE parent_task_id = ?
                    ORDER BY child_task_id
                    """,
                    (task_id,),
                )
            ).fetchall()
        return [
            ActivitySummaryDependency(
                parent_task_id=row["parent_task_id"],
                child_task_id=row["child_task_id"],
            )
            for row in rows
        ]

    async def recover_expired_leases(
        self,
        *,
        now: datetime,
        include_unexpired: bool = False,
    ) -> list[ActivitySummaryTask]:
        observed = require_aware(now)
        recovered: list[ActivitySummaryTask] = []
        async with self.database.transaction() as connection:
            if include_unexpired:
                rows = await (
                    await connection.execute(
                        """
                        SELECT config FROM activity_summary_tasks
                        WHERE status = ?
                        ORDER BY window_end, id
                        """,
                        (SummaryTaskStatus.RUNNING.value,),
                    )
                ).fetchall()
            else:
                rows = await (
                    await connection.execute(
                        """
                        SELECT config FROM activity_summary_tasks
                        WHERE status = ? AND lease_expires_at IS NOT NULL
                            AND lease_expires_at <= ?
                        ORDER BY window_end, id
                        """,
                        (SummaryTaskStatus.RUNNING.value, observed.isoformat()),
                    )
                ).fetchall()
            for row in rows:
                task = self._task_from_row(row).model_copy(
                    update={
                        "status": SummaryTaskStatus.NEEDS_RETRY,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "next_retry_at": observed,
                        "error_code": "summary_lease_expired",
                        "updated_at": observed,
                    }
                )
                await self._update_task_in(connection, task)
                await self._fail_running_attempt_in(
                    connection,
                    task.id,
                    error_code="summary_lease_expired",
                    now=observed,
                )
                recovered.append(task)
        return recovered

    async def requeue_failed_tasks(self, *, now: datetime) -> list[ActivitySummaryTask]:
        """Retry legacy permanent failures once, except explicit-regeneration failures."""

        observed = require_aware(now)
        requeued: list[ActivitySummaryTask] = []
        async with self.database.transaction() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT config FROM activity_summary_tasks
                    WHERE status = ?
                    ORDER BY window_end, task_type, id
                    """,
                    (SummaryTaskStatus.FAILED.value,),
                )
            ).fetchall()
            for row in rows:
                task = self._task_from_row(row)
                if task.error_code in _EXPLICIT_REGENERATION_ERROR_CODES:
                    continue
                updated = task.model_copy(
                    update={
                        "status": SummaryTaskStatus.NEEDS_RETRY,
                        "next_retry_at": observed,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "updated_at": observed,
                    }
                )
                await self._update_task_in(connection, updated)
                requeued.append(updated)
        return requeued

    async def task_ids(
        self,
        *,
        candidate_ids: set[str] | None = None,
    ) -> set[str]:
        async with self.database.connect() as connection:
            if candidate_ids is None:
                rows = await (
                    await connection.execute("SELECT id FROM activity_summary_tasks")
                ).fetchall()
                return {str(row["id"]) for row in rows}
            existing: set[str] = set()
            ordered = sorted(candidate_ids)
            for offset in range(0, len(ordered), 500):
                batch = ordered[offset : offset + 500]
                placeholders = ", ".join("?" for _item in batch)
                rows = await (
                    await connection.execute(
                        f"""
                        SELECT id FROM activity_summary_tasks
                        WHERE id IN ({placeholders})
                        """,
                        batch,
                    )
                ).fetchall()
                existing.update(str(row["id"]) for row in rows)
        return existing

    async def list_due_tasks(
        self,
        *,
        now: datetime,
        category_rule_version: str | None,
        limit: int = 100,
    ) -> list[ActivitySummaryTask]:
        observed = require_aware(now)
        if limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        current_rules = category_rule_version
        final_window_cutoff = observed - FINAL_GRACE
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT config FROM activity_summary_tasks
                    WHERE (
                        status = ? AND not_before <= ?
                    ) OR (
                        status = ?
                        AND COALESCE(next_retry_at, not_before) <= ?
                    ) OR (
                        status = ?
                        AND (
                            (
                                ? IS NOT NULL
                                AND category_rule_version IS NOT ?
                                AND COALESCE(next_retry_at, not_before) <= ?
                            ) OR (
                                (finality IS NULL OR finality != ?)
                                AND window_end <= ?
                                AND COALESCE(next_retry_at, not_before) <= ?
                            )
                        )
                    )
                    ORDER BY window_end,
                        CASE task_type
                            WHEN 'stage_6h' THEN 0
                            WHEN 'daily_24h' THEN 1
                            WHEN 'weekly' THEN 2
                            WHEN 'biweekly' THEN 3
                            WHEN 'monthly' THEN 4
                            ELSE 5
                        END,
                        id
                    LIMIT ?
                    """,
                    (
                        SummaryTaskStatus.PENDING.value,
                        observed.isoformat(),
                        SummaryTaskStatus.NEEDS_RETRY.value,
                        observed.isoformat(),
                        SummaryTaskStatus.COMPLETED.value,
                        current_rules,
                        current_rules,
                        observed.isoformat(),
                        SummaryFinality.FINAL.value,
                        final_window_cutoff.isoformat(),
                        observed.isoformat(),
                        limit,
                    ),
                )
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    async def claim_task(
        self,
        task_id: str,
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta = timedelta(minutes=10),
        category_rule_version: str | None = None,
    ) -> tuple[ActivitySummaryTask, ActivitySummaryAttempt] | None:
        if not lease_owner:
            raise ValueError("lease_owner is required")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        observed = require_aware(now)
        async with self.database.transaction() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_summary_tasks WHERE id = ?",
                    (task_id,),
                )
            ).fetchone()
            if row is None:
                raise LookupError(task_id)
            task = self._task_from_row(row)
            if not self._task_is_due(
                task,
                now=observed,
                category_rule_version=category_rule_version,
            ):
                return None
            attempt_number = task.attempt_count + 1
            claimed = task.model_copy(
                update={
                    "status": SummaryTaskStatus.RUNNING,
                    "attempt_count": attempt_number,
                    "lease_owner": lease_owner,
                    "lease_expires_at": observed + lease_duration,
                    "next_retry_at": None,
                    "error_code": None,
                    "updated_at": observed,
                }
            )
            await self._update_task_in(connection, claimed)
            attempt = ActivitySummaryAttempt(
                id=self._attempt_id(task.id, attempt_number),
                task_id=task.id,
                attempt_number=attempt_number,
                status=SummaryAttemptStatus.RUNNING,
                started_at=observed,
            )
            await connection.execute(
                """
                INSERT INTO activity_summary_attempts(
                    id, task_id, attempt_number, status, config, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    attempt.id,
                    attempt.task_id,
                    attempt.attempt_number,
                    attempt.status.value,
                    attempt.model_dump_json(),
                    attempt.started_at.isoformat(),
                ),
            )
            return claimed, attempt

    async def complete_attempt(
        self,
        *,
        task_id: str,
        attempt_id: str,
        revision: ActivitySummaryRevision,
        now: datetime,
        next_retry_at: datetime | None = None,
    ) -> tuple[ActivitySummaryTask, ActivitySummaryRevision]:
        observed = require_aware(now)
        retry_at = require_aware(next_retry_at) if next_retry_at is not None else None
        async with self.database.transaction() as connection:
            task = await self._required_task_in(connection, task_id)
            attempt = await self._required_attempt_in(connection, attempt_id)
            if attempt.task_id != task_id:
                raise ValueError("summary attempt belongs to another task")
            revision_key = self._revision_key(task_id, revision)
            existing = await self._revision_by_key_in(connection, revision_key)
            if attempt.status is SummaryAttemptStatus.COMPLETED and existing is not None:
                return task, existing
            if (
                task.status is not SummaryTaskStatus.RUNNING
                or attempt.status is not SummaryAttemptStatus.RUNNING
                or task.attempt_count != attempt.attempt_number
            ):
                if existing is not None:
                    return task, existing
                raise StaleActivitySummaryAttempt(attempt_id)
            if existing is None:
                number = task.current_revision + 1
                revision_id = hashlib.sha256(
                    f"{task_id}|{number}|{revision_key}".encode()
                ).hexdigest()
                stored_revision = revision.model_copy(
                    update={
                        "id": revision_id,
                        "task_id": task_id,
                        "revision_number": number,
                        "completed_at": observed,
                    }
                )
                await connection.execute(
                    """
                    INSERT INTO activity_summary_revisions(
                        id, task_id, revision_number, finality, source_watermark,
                        category_rule_version, revision_key, config, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stored_revision.id,
                        stored_revision.task_id,
                        stored_revision.revision_number,
                        stored_revision.finality.value,
                        stored_revision.source_watermark,
                        stored_revision.category_rule_version,
                        revision_key,
                        stored_revision.model_dump_json(),
                        stored_revision.completed_at.isoformat(),
                    ),
                )
                await connection.execute(
                    """
                    INSERT INTO activity_statistics(revision_id, config)
                    VALUES (?, ?)
                    """,
                    (
                        stored_revision.id,
                        stored_revision.statistics.model_dump_json(),
                    ),
                )
                await self._insert_evidence_refs_in(
                    connection,
                    owner_id=stored_revision.id,
                    evidence=stored_revision.evidence_refs,
                )
            else:
                stored_revision = existing

            completed_attempt = attempt.model_copy(
                update={
                    "status": SummaryAttemptStatus.COMPLETED,
                    "completed_at": observed,
                    "request_digest": stored_revision.request_digest,
                    "provider": stored_revision.provider,
                    "model": stored_revision.model,
                    "requested_provider": stored_revision.requested_provider,
                    "requested_model": stored_revision.requested_model,
                    "configuration_version": stored_revision.configuration_version,
                    "prompt_version": stored_revision.prompt_version,
                    "redaction_count": stored_revision.redaction_count,
                    "usage": stored_revision.usage,
                    "fallback_reason": stored_revision.fallback_reason,
                    "error_code": None,
                }
            )
            await self._update_attempt_in(connection, completed_attempt)
            completed_task = task.model_copy(
                update={
                    "status": SummaryTaskStatus.COMPLETED,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "next_retry_at": retry_at,
                    "finality": stored_revision.finality,
                    "completed_at": observed,
                    "error_code": None,
                    "regeneration_reason": None,
                    "category_rule_version": stored_revision.category_rule_version,
                    "provider": stored_revision.provider,
                    "model": stored_revision.model,
                    "configuration_version": stored_revision.configuration_version,
                    "prompt_version": stored_revision.prompt_version,
                    "statistics_version": stored_revision.statistics_version,
                    "current_revision": stored_revision.revision_number,
                    "source_watermark": stored_revision.source_watermark,
                    "updated_at": observed,
                }
            )
            await self._update_task_in(connection, completed_task)
            return completed_task, stored_revision

    async def fail_attempt(
        self,
        *,
        task_id: str,
        attempt_id: str,
        error_code: str,
        now: datetime,
        retryable: bool = True,
        retry_delay: timedelta = timedelta(minutes=5),
        failure_stage: ModelResponseFailureStage | None = None,
    ) -> ActivitySummaryTask:
        if not error_code:
            raise ValueError("error_code is required")
        observed = require_aware(now)
        async with self.database.transaction() as connection:
            task = await self._required_task_in(connection, task_id)
            attempt = await self._required_attempt_in(connection, attempt_id)
            if (
                task.status is not SummaryTaskStatus.RUNNING
                or attempt.status is not SummaryAttemptStatus.RUNNING
                or task.attempt_count != attempt.attempt_number
            ):
                return task
            failed_attempt = attempt.model_copy(
                update={
                    "status": SummaryAttemptStatus.FAILED,
                    "completed_at": observed,
                    "error_code": error_code,
                    "failure_stage": failure_stage,
                }
            )
            await self._update_attempt_in(connection, failed_attempt)
            failed_task = task.model_copy(
                update={
                    "status": (
                        SummaryTaskStatus.NEEDS_RETRY if retryable else SummaryTaskStatus.FAILED
                    ),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "next_retry_at": observed + retry_delay if retryable else None,
                    "error_code": error_code,
                    "updated_at": observed,
                }
            )
            await self._update_task_in(connection, failed_task)
            return failed_task

    async def mark_legacy_rule_revisions(
        self,
        *,
        current_category_rule_version: str,
    ) -> int:
        changed = 0
        async with self.database.transaction() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT id, config FROM activity_summary_revisions
                    """,
                )
            ).fetchall()
            for row in rows:
                revision = self._revision_from_row(row)
                legacy = revision.category_rule_version != current_category_rule_version
                if revision.legacy_rules is legacy:
                    continue
                updated = revision.model_copy(update={"legacy_rules": legacy})
                await connection.execute(
                    "UPDATE activity_summary_revisions SET config = ? WHERE id = ?",
                    (updated.model_dump_json(), updated.id),
                )
                changed += 1
        return changed

    async def request_regeneration(
        self,
        task_id: str,
        *,
        now: datetime,
        reason: str,
    ) -> ActivitySummaryTask:
        observed = require_aware(now)
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 200:
            raise ValueError("regeneration reason must be between 1 and 200 characters")
        async with self.database.transaction() as connection:
            task = await self._required_task_in(connection, task_id)
            if task.status is SummaryTaskStatus.RUNNING:
                raise ValueError("a running summary task cannot be regenerated")
            updated = task.model_copy(
                update={
                    "status": SummaryTaskStatus.NEEDS_RETRY,
                    "next_retry_at": observed,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "error_code": None,
                    "regeneration_reason": normalized_reason,
                    "updated_at": observed,
                }
            )
            await self._update_task_in(connection, updated)
            return updated

    async def history_count(self) -> int:
        tables = (
            "activity_evidence_refs",
            "activity_statistics",
            "activity_summary_dependencies",
            "activity_summary_revisions",
            "activity_summary_attempts",
            "activity_summary_tasks",
        )
        async with self.database.connect() as connection:
            total = 0
            for table in tables:
                row = await (
                    await connection.execute(f"SELECT COUNT(*) AS count FROM {table}")
                ).fetchone()
                total += int(row["count"])
        return total

    async def reset_history(self, *, now: datetime | None = None) -> int:
        from datetime import UTC

        observed = require_aware(now or datetime.now(UTC))
        previous = await self.source_state()
        count = await self.history_count()
        async with self.database.transaction() as connection:
            for table in (
                "activity_evidence_refs",
                "activity_statistics",
                "activity_summary_dependencies",
                "activity_summary_revisions",
                "activity_summary_attempts",
                "activity_summary_tasks",
                "activity_category_rule_versions",
            ):
                await connection.execute(f"DELETE FROM {table}")
            tombstone = (
                previous.model_copy(
                    update={
                        "history_cutoff": observed,
                        "last_reconciled_at": None,
                        "category_rule_version": None,
                        "error_code": None,
                        "checked_at": observed,
                    }
                )
                if previous is not None
                else ActivitySourceState(
                    health="degraded",
                    checked_at=observed,
                    history_cutoff=observed,
                    error_code="activitywatch_not_checked",
                )
            )
            await connection.execute(
                """
                INSERT INTO activity_source_state(singleton_id, health, config, updated_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    health = excluded.health,
                    config = excluded.config,
                    updated_at = excluded.updated_at
                """,
                (
                    tombstone.health.value,
                    tombstone.model_dump_json(),
                    observed.isoformat(),
                ),
            )
        return count

    async def clear_history_cutoff(self, *, now: datetime) -> ActivitySourceState:
        observed = require_aware(now)
        state = await self.source_state()
        if state is None:
            state = ActivitySourceState(
                health="degraded",
                checked_at=observed,
                error_code="activitywatch_not_checked",
            )
        updated = state.model_copy(
            update={
                "history_cutoff": None,
                "last_reconciled_at": None,
                "checked_at": observed,
            }
        )
        return await self.save_source_state(
            updated,
            preserve_history_cutoff=False,
        )

    async def get_task(self, task_id: str) -> ActivitySummaryTask | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_summary_tasks WHERE id = ?",
                    (task_id,),
                )
            ).fetchone()
        return self._task_from_row(row) if row else None

    async def list_tasks(
        self,
        *,
        statuses: tuple[SummaryTaskStatus, ...] | None = None,
        limit: int = 500,
    ) -> list[ActivitySummaryTask]:
        if limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        query = "SELECT config FROM activity_summary_tasks"
        parameters: list[Any] = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query += f" WHERE status IN ({placeholders})"
            parameters.extend(status.value for status in statuses)
        query += " ORDER BY window_end DESC, task_type, id LIMIT ?"
        parameters.append(limit)
        async with self.database.connect() as connection:
            rows = await (await connection.execute(query, parameters)).fetchall()
        return [self._task_from_row(row) for row in rows]

    async def list_attempts(self, task_id: str) -> list[ActivitySummaryAttempt]:
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT config FROM activity_summary_attempts
                    WHERE task_id = ?
                    ORDER BY attempt_number, id
                    """,
                    (task_id,),
                )
            ).fetchall()
        return [self._attempt_from_row(row) for row in rows]

    async def get_revision(self, revision_id: str) -> ActivitySummaryRevision | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_summary_revisions WHERE id = ?",
                    (revision_id,),
                )
            ).fetchone()
        return self._revision_from_row(row) if row else None

    async def get_summary(self, summary_id: str) -> ActivitySummaryRevision | None:
        revision = await self.get_revision(summary_id)
        if revision is not None:
            return revision
        return await self.latest_revision(summary_id)

    async def latest_revision(self, task_id: str) -> ActivitySummaryRevision | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT config FROM activity_summary_revisions
                    WHERE task_id = ?
                    ORDER BY revision_number DESC LIMIT 1
                    """,
                    (task_id,),
                )
            ).fetchone()
        return self._revision_from_row(row) if row else None

    async def summary_history(
        self,
        *,
        task_type: SummaryTaskType | None = None,
        limit: int = 100,
    ) -> list[ActivitySummaryRevision]:
        if limit < 1 or limit > 1_000:
            raise ValueError("limit must be between 1 and 1000")
        query = """
            SELECT revision.config
            FROM activity_summary_revisions AS revision
            JOIN activity_summary_tasks AS task ON task.id = revision.task_id
        """
        parameters: list[Any] = []
        if task_type is not None:
            query += " WHERE task.task_type = ?"
            parameters.append(task_type.value)
        query += " ORDER BY task.window_end DESC, revision.revision_number DESC LIMIT ?"
        parameters.append(limit)
        async with self.database.connect() as connection:
            rows = await (await connection.execute(query, parameters)).fetchall()
        return [self._revision_from_row(row) for row in rows]

    async def trends(
        self,
        *,
        task_type: SummaryTaskType | None = None,
        limit: int = 90,
    ) -> list[ActivityTrendPoint]:
        revisions = await self.summary_history(task_type=task_type, limit=limit * 3)
        latest_by_task: dict[str, ActivitySummaryRevision] = {}
        for revision in revisions:
            latest_by_task.setdefault(revision.task_id, revision)
        points = [
            ActivityTrendPoint(
                task_type=(await self._required_task(revision.task_id)).task_type,
                window_start=revision.statistics.window_start,
                window_end=revision.statistics.window_end,
                active_seconds=revision.statistics.active_seconds,
                afk_seconds=revision.statistics.afk_seconds,
                app_switch_count=revision.statistics.app_switch_count,
                category_switch_count=revision.statistics.category_switch_count,
                context_switch_count=revision.statistics.context_switch_count,
                dominant_category=(
                    max(
                        revision.statistics.category_seconds.items(),
                        key=lambda item: (item[1], item[0]),
                    )[0]
                    if revision.statistics.category_seconds
                    else None
                ),
                finality=revision.finality,
            )
            for revision in latest_by_task.values()
        ]
        points.sort(key=lambda point: (point.window_start, point.task_type.value))
        return points[-limit:]

    async def _required_task(self, task_id: str) -> ActivitySummaryTask:
        task = await self.get_task(task_id)
        if task is None:
            raise LookupError(task_id)
        return task

    @staticmethod
    def _task_is_due(
        task: ActivitySummaryTask,
        *,
        now: datetime,
        category_rule_version: str | None,
    ) -> bool:
        if task.status is SummaryTaskStatus.RUNNING:
            return False
        due_at = task.next_retry_at or task.not_before
        if task.status is SummaryTaskStatus.PENDING:
            return now >= task.not_before
        if task.status is SummaryTaskStatus.NEEDS_RETRY:
            return now >= due_at
        if task.status is SummaryTaskStatus.FAILED:
            return False
        if task.status is not SummaryTaskStatus.COMPLETED:
            return False
        legacy_rules = (
            category_rule_version is not None
            and task.category_rule_version != category_rule_version
        )
        non_final = task.finality is not SummaryFinality.FINAL
        if legacy_rules:
            return now >= due_at
        if non_final:
            return now >= max(task.window_end + FINAL_GRACE, due_at)
        return False

    @staticmethod
    def _attempt_id(task_id: str, attempt_number: int) -> str:
        return hashlib.sha256(f"{task_id}|{attempt_number}".encode()).hexdigest()

    @staticmethod
    def _revision_key(
        task_id: str,
        revision: ActivitySummaryRevision,
    ) -> str:
        return canonical_digest(
            {
                "task_id": task_id,
                "generation_id": revision.generation_id,
                "generation_reason": revision.generation_reason,
                "finality": revision.finality.value,
                "source_watermark": revision.source_watermark,
                "category_rule_version": revision.category_rule_version,
                "provider": revision.provider,
                "model": revision.model,
                "requested_provider": revision.requested_provider,
                "requested_model": revision.requested_model,
                "configuration_version": revision.configuration_version,
                "summary_settings_version": revision.summary_settings_version,
                "prompt_version": revision.prompt_version,
                "statistics_version": revision.statistics_version,
                "request_digest": revision.request_digest,
                "summary_text": revision.summary_text,
                "fallback_reason": revision.fallback_reason,
            }
        )

    @staticmethod
    def _task_values(task: ActivitySummaryTask) -> tuple[Any, ...]:
        return (
            task.id,
            task.task_type.value,
            task.window_start.isoformat(),
            task.window_end.isoformat(),
            task.timezone,
            task.boundary_policy_version,
            task.status.value,
            task.finality.value if task.finality is not None else None,
            task.attempt_count,
            task.not_before.isoformat(),
            task.next_retry_at.isoformat() if task.next_retry_at else None,
            task.lease_owner,
            task.lease_expires_at.isoformat() if task.lease_expires_at else None,
            task.current_revision,
            task.category_rule_version,
            task.source_watermark,
            task.model_dump_json(),
            task.created_at.isoformat(),
            task.updated_at.isoformat(),
        )

    @staticmethod
    async def _update_task_in(connection, task: ActivitySummaryTask) -> None:
        cursor = await connection.execute(
            """
            UPDATE activity_summary_tasks SET
                status = ?, finality = ?, attempt_count = ?, not_before = ?,
                next_retry_at = ?, lease_owner = ?, lease_expires_at = ?,
                current_revision = ?, category_rule_version = ?,
                source_watermark = ?, config = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                task.status.value,
                task.finality.value if task.finality else None,
                task.attempt_count,
                task.not_before.isoformat(),
                task.next_retry_at.isoformat() if task.next_retry_at else None,
                task.lease_owner,
                task.lease_expires_at.isoformat() if task.lease_expires_at else None,
                task.current_revision,
                task.category_rule_version,
                task.source_watermark,
                task.model_dump_json(),
                task.updated_at.isoformat(),
                task.id,
            ),
        )
        if cursor.rowcount != 1:
            raise LookupError(task.id)

    @staticmethod
    async def _update_attempt_in(connection, attempt: ActivitySummaryAttempt) -> None:
        cursor = await connection.execute(
            """
            UPDATE activity_summary_attempts
            SET status = ?, config = ?, completed_at = ?
            WHERE id = ?
            """,
            (
                attempt.status.value,
                attempt.model_dump_json(),
                attempt.completed_at.isoformat() if attempt.completed_at else None,
                attempt.id,
            ),
        )
        if cursor.rowcount != 1:
            raise LookupError(attempt.id)

    @staticmethod
    async def _fail_running_attempt_in(
        connection,
        task_id: str,
        *,
        error_code: str,
        now: datetime,
    ) -> None:
        row = await (
            await connection.execute(
                """
                SELECT config FROM activity_summary_attempts
                WHERE task_id = ? AND status = ?
                ORDER BY attempt_number DESC LIMIT 1
                """,
                (task_id, SummaryAttemptStatus.RUNNING.value),
            )
        ).fetchone()
        if row is None:
            return
        attempt = ActivityRepository._attempt_from_row(row).model_copy(
            update={
                "status": SummaryAttemptStatus.FAILED,
                "completed_at": now,
                "error_code": error_code,
            }
        )
        await ActivityRepository._update_attempt_in(connection, attempt)

    @staticmethod
    async def _insert_evidence_refs_in(
        connection,
        *,
        owner_id: str,
        evidence,
    ) -> None:
        for ordinal, reference in enumerate(evidence):
            await connection.execute(
                """
                INSERT OR IGNORE INTO activity_evidence_refs(
                    owner_type, owner_id, ordinal, bucket_id, event_id,
                    event_timestamp, event_digest, config
                ) VALUES ('revision', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_id,
                    ordinal,
                    reference.bucket_id,
                    reference.event_id,
                    reference.event_timestamp.isoformat(),
                    reference.event_digest,
                    reference.model_dump_json(),
                ),
            )

    @staticmethod
    def _merge_source_state(
        incoming: ActivitySourceState,
        *,
        existing: ActivitySourceState | None,
        preserve_history_cutoff: bool,
    ) -> ActivitySourceState:
        updates: dict[str, datetime | None] = {}
        if existing is not None and preserve_history_cutoff:
            cutoffs = [
                value
                for value in (existing.history_cutoff, incoming.history_cutoff)
                if value is not None
            ]
            updates["history_cutoff"] = max(cutoffs) if cutoffs else None
        return incoming.model_copy(update=updates)

    @staticmethod
    async def _save_source_state_in(connection, state: ActivitySourceState) -> None:
        await connection.execute(
            """
            INSERT INTO activity_source_state(singleton_id, health, config, updated_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(singleton_id) DO UPDATE SET
                health = excluded.health,
                config = excluded.config,
                updated_at = excluded.updated_at
            """,
            (
                state.health.value,
                state.model_dump_json(),
                state.checked_at.isoformat(),
            ),
        )

    @staticmethod
    async def _required_task_in(connection, task_id: str) -> ActivitySummaryTask:
        row = await (
            await connection.execute(
                "SELECT config FROM activity_summary_tasks WHERE id = ?",
                (task_id,),
            )
        ).fetchone()
        if row is None:
            raise LookupError(task_id)
        return ActivityRepository._task_from_row(row)

    @staticmethod
    async def _required_attempt_in(
        connection,
        attempt_id: str,
    ) -> ActivitySummaryAttempt:
        row = await (
            await connection.execute(
                "SELECT config FROM activity_summary_attempts WHERE id = ?",
                (attempt_id,),
            )
        ).fetchone()
        if row is None:
            raise LookupError(attempt_id)
        return ActivityRepository._attempt_from_row(row)

    @staticmethod
    async def _revision_by_key_in(
        connection,
        revision_key: str,
    ) -> ActivitySummaryRevision | None:
        row = await (
            await connection.execute(
                "SELECT config FROM activity_summary_revisions WHERE revision_key = ?",
                (revision_key,),
            )
        ).fetchone()
        return ActivityRepository._revision_from_row(row) if row else None

    @staticmethod
    def _task_from_row(row: Any) -> ActivitySummaryTask:
        return ActivitySummaryTask.model_validate_json(row["config"])

    @staticmethod
    def _attempt_from_row(row: Any) -> ActivitySummaryAttempt:
        return ActivitySummaryAttempt.model_validate_json(row["config"])

    @staticmethod
    def _revision_from_row(row: Any) -> ActivitySummaryRevision:
        return ActivitySummaryRevision.model_validate_json(row["config"])
