from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from weatherflow.automations.models import (
    Automation,
    AutomationRunLink,
    AutomationStatus,
    RunLinkStatus,
    require_aware,
)
from weatherflow.storage import Database


class AutomationNotFoundError(LookupError):
    pass


class AutomationVersionConflict(RuntimeError):
    pass


class AutomationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(self, automation: Automation) -> None:
        try:
            async with self.database.transaction() as connection:
                await connection.execute(
                    """
                    INSERT INTO automations(
                        id, workspace_id, name, status, next_run_at, config,
                        version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._automation_values(automation),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"automation already exists: {automation.id}") from error

    async def get(self, automation_id: str) -> Automation | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM automations WHERE id = ?", (automation_id,)
                )
            ).fetchone()
        return self._automation_from_row(row) if row else None

    async def list(
        self,
        workspace_id: str,
        *,
        status: AutomationStatus | None = None,
    ) -> list[Automation]:
        async with self.database.connect() as connection:
            if status is None:
                query = (
                    "SELECT config FROM automations WHERE workspace_id = ? "
                    "ORDER BY updated_at DESC, id DESC"
                )
                parameters: tuple[object, ...] = (workspace_id,)
            else:
                query = (
                    "SELECT config FROM automations "
                    "WHERE workspace_id = ? AND status = ? "
                    "ORDER BY updated_at DESC, id DESC"
                )
                parameters = (workspace_id, status.value)
            rows = await (await connection.execute(query, parameters)).fetchall()
        return [self._automation_from_row(row) for row in rows]

    async def list_due(self, now: datetime, *, limit: int = 100) -> list[Automation]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        observed = require_aware(now)
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT config FROM automations
                    WHERE status = ? AND next_run_at IS NOT NULL AND next_run_at <= ?
                    ORDER BY next_run_at, id LIMIT ?
                    """,
                    (AutomationStatus.ENABLED.value, observed.isoformat(), limit),
                )
            ).fetchall()
        return [self._automation_from_row(row) for row in rows]

    async def update(self, automation: Automation, *, expected_version: int) -> None:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE automations
                SET name = ?, status = ?, next_run_at = ?, config = ?,
                    version = ?, updated_at = ?
                WHERE id = ? AND version = ?
                """,
                (
                    automation.name,
                    automation.status.value,
                    self._iso(automation.next_run_at),
                    automation.model_dump_json(),
                    automation.version,
                    automation.updated_at.isoformat(),
                    automation.id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise AutomationVersionConflict(automation.id)

    async def delete(self, automation_id: str, *, expected_version: int) -> None:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "DELETE FROM automations WHERE id = ? AND version = ?",
                (automation_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise AutomationVersionConflict(automation_id)

    async def claim_scheduled(
        self,
        automation_id: str,
        *,
        now: datetime,
    ) -> AutomationRunLink | None:
        observed = require_aware(now)
        async with self.database.transaction() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM automations WHERE id = ?", (automation_id,)
                )
            ).fetchone()
            if row is None:
                return None
            automation = self._automation_from_row(row)
            if (
                automation.status is not AutomationStatus.ENABLED
                or automation.next_run_at is None
                or automation.next_run_at > observed
            ):
                return None
            scheduled_for = automation.next_run_at
            link = AutomationRunLink.scheduled(
                automation=automation,
                scheduled_for=scheduled_for,
                now=observed,
            )
            updated = automation.model_copy(
                update={
                    "next_run_at": automation.schedule.next_after(observed),
                    "last_run_at": observed,
                    "version": automation.version + 1,
                    "updated_at": observed,
                }
            )
            cursor = await connection.execute(
                """
                UPDATE automations
                SET next_run_at = ?, config = ?, version = ?, updated_at = ?
                WHERE id = ? AND version = ? AND next_run_at = ? AND status = ?
                """,
                (
                    self._iso(updated.next_run_at),
                    updated.model_dump_json(),
                    updated.version,
                    updated.updated_at.isoformat(),
                    automation.id,
                    automation.version,
                    scheduled_for.isoformat(),
                    AutomationStatus.ENABLED.value,
                ),
            )
            if cursor.rowcount != 1:
                return None
            await self._insert_link(connection, link)
            return link

    async def claim_manual(
        self,
        automation_id: str,
        *,
        now: datetime,
    ) -> AutomationRunLink:
        observed = require_aware(now)
        async with self.database.transaction() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM automations WHERE id = ?", (automation_id,)
                )
            ).fetchone()
            if row is None:
                raise AutomationNotFoundError(automation_id)
            automation = self._automation_from_row(row)
            link = AutomationRunLink.manual(automation=automation, now=observed)
            updated = Automation.model_validate(
                {
                    **automation.model_dump(),
                    "last_run_at": observed,
                    "version": automation.version + 1,
                    "updated_at": observed,
                }
            )
            cursor = await connection.execute(
                """
                UPDATE automations
                SET config = ?, version = ?, updated_at = ?
                WHERE id = ? AND version = ?
                """,
                (
                    updated.model_dump_json(),
                    updated.version,
                    updated.updated_at.isoformat(),
                    automation.id,
                    automation.version,
                ),
            )
            if cursor.rowcount != 1:
                raise AutomationVersionConflict(automation.id)
            await self._insert_link(connection, link)
            return link

    async def mark_submitted(
        self,
        link_id: str,
        *,
        run_id: str,
        now: datetime,
    ) -> AutomationRunLink:
        observed = require_aware(now)
        return await self._finish_link(
            link_id,
            status=RunLinkStatus.SUBMITTED,
            run_id=run_id,
            error_code=None,
            now=observed,
        )

    async def mark_failed(
        self,
        link_id: str,
        *,
        error_code: str,
        now: datetime,
    ) -> AutomationRunLink:
        observed = require_aware(now)
        return await self._finish_link(
            link_id,
            status=RunLinkStatus.FAILED,
            run_id=None,
            error_code=error_code,
            now=observed,
        )

    async def list_pending(self, *, limit: int = 100) -> list[AutomationRunLink]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT config FROM automation_run_links
                    WHERE status = ? ORDER BY created_at, id LIMIT ?
                    """,
                    (RunLinkStatus.PENDING.value, limit),
                )
            ).fetchall()
        return [self._link_from_row(row) for row in rows]

    async def list_history(
        self,
        automation_id: str,
        *,
        limit: int = 100,
    ) -> list[AutomationRunLink]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT config FROM automation_run_links
                    WHERE automation_id = ? ORDER BY created_at DESC, id DESC LIMIT ?
                    """,
                    (automation_id, limit),
                )
            ).fetchall()
        return [self._link_from_row(row) for row in rows]

    async def _finish_link(
        self,
        link_id: str,
        *,
        status: RunLinkStatus,
        run_id: str | None,
        error_code: str | None,
        now: datetime,
    ) -> AutomationRunLink:
        async with self.database.transaction() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM automation_run_links WHERE id = ?", (link_id,)
                )
            ).fetchone()
            if row is None:
                raise LookupError(link_id)
            current = self._link_from_row(row)
            if current.status is not RunLinkStatus.PENDING:
                return current
            updated = current.model_copy(
                update={
                    "status": status,
                    "run_id": run_id,
                    "error_code": error_code,
                    "updated_at": now,
                }
            )
            cursor = await connection.execute(
                """
                UPDATE automation_run_links
                SET status = ?, run_id = ?, error_code = ?, config = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    status.value,
                    run_id,
                    error_code,
                    updated.model_dump_json(),
                    now.isoformat(),
                    link_id,
                    RunLinkStatus.PENDING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"automation link changed concurrently: {link_id}")
            return updated

    @staticmethod
    async def _insert_link(connection: Any, link: AutomationRunLink) -> None:
        await connection.execute(
            """
            INSERT INTO automation_run_links(
                id, automation_id, workspace_id, trigger, scheduled_for,
                client_request_id, status, run_id, error_code, config,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                link.id,
                link.automation_id,
                link.workspace_id,
                link.trigger.value,
                link.scheduled_for.isoformat(),
                link.client_request_id,
                link.status.value,
                link.run_id,
                link.error_code,
                link.model_dump_json(),
                link.created_at.isoformat(),
                link.updated_at.isoformat(),
            ),
        )

    @staticmethod
    def _automation_values(automation: Automation) -> tuple[object, ...]:
        return (
            automation.id,
            automation.workspace_id,
            automation.name,
            automation.status.value,
            AutomationRepository._iso(automation.next_run_at),
            automation.model_dump_json(),
            automation.version,
            automation.created_at.isoformat(),
            automation.updated_at.isoformat(),
        )

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _automation_from_row(row: Any) -> Automation:
        return Automation.model_validate_json(row["config"])

    @staticmethod
    def _link_from_row(row: Any) -> AutomationRunLink:
        return AutomationRunLink.model_validate_json(row["config"])
