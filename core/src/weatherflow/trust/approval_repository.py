import sqlite3
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from weatherflow.storage import Database
from weatherflow.trust.models import Approval, ApprovalStatus


class DuplicateApprovalError(ValueError):
    pass


class ApprovalNotFoundError(LookupError):
    pass


class ApprovalVersionConflict(RuntimeError):
    pass


class ApprovalRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_in(self, connection: aiosqlite.Connection, approval: Approval) -> None:
        try:
            await connection.execute(
                """
                INSERT INTO approvals(
                    id, action_id, run_id, status, requested_at, decided_at,
                    decided_by, rationale, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(approval),
            )
        except sqlite3.IntegrityError as error:
            if "UNIQUE constraint failed" in str(error):
                raise DuplicateApprovalError(approval.action_id) from error
            raise

    async def get(self, approval_id: str) -> Approval | None:
        async with self.database.connect() as connection:
            return await self.get_in(connection, approval_id)

    async def get_in(self, connection: aiosqlite.Connection, approval_id: str) -> Approval | None:
        row = await (
            await connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,))
        ).fetchone()
        return self._from_row(row) if row else None

    async def get_by_action_id(self, action_id: str) -> Approval | None:
        async with self.database.connect() as connection:
            return await self.get_by_action_id_in(connection, action_id)

    async def get_by_action_id_in(
        self, connection: aiosqlite.Connection, action_id: str
    ) -> Approval | None:
        row = await (
            await connection.execute("SELECT * FROM approvals WHERE action_id = ?", (action_id,))
        ).fetchone()
        return self._from_row(row) if row else None

    async def transition_in(
        self,
        connection: aiosqlite.Connection,
        approval_id: str,
        target: ApprovalStatus,
        expected_version: int,
        *,
        decided_by: str,
        rationale: str | None = None,
    ) -> Approval:
        current = await self.get_in(connection, approval_id)
        if current is None:
            raise ApprovalNotFoundError(approval_id)
        if current.version != expected_version:
            raise ApprovalVersionConflict(approval_id)
        current.status.require_transition(target)
        cursor = await connection.execute(
            """
            UPDATE approvals
            SET status = ?, decided_at = ?, decided_by = ?, rationale = ?,
                version = version + 1
            WHERE id = ? AND version = ?
            """,
            (
                target.value,
                datetime.now(UTC).isoformat(),
                decided_by,
                rationale,
                approval_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise ApprovalVersionConflict(approval_id)
        updated = await self.get_in(connection, approval_id)
        if updated is None:
            raise ApprovalNotFoundError(approval_id)
        return updated

    @staticmethod
    def _values(approval: Approval) -> tuple[Any, ...]:
        return (
            approval.id,
            approval.action_id,
            approval.run_id,
            approval.status.value,
            approval.requested_at.isoformat(),
            approval.decided_at.isoformat() if approval.decided_at else None,
            approval.decided_by,
            approval.rationale,
            approval.version,
        )

    @staticmethod
    def _from_row(row: Any) -> Approval:
        return Approval.model_validate(
            {
                "id": row["id"],
                "action_id": row["action_id"],
                "run_id": row["run_id"],
                "status": row["status"],
                "requested_at": row["requested_at"],
                "decided_at": row["decided_at"],
                "decided_by": row["decided_by"],
                "rationale": row["rationale"],
                "version": row["version"],
            }
        )
