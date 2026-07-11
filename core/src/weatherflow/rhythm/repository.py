from datetime import UTC, datetime
from typing import Any

import aiosqlite

from weatherflow.rhythm.models import HumanStateSnapshot
from weatherflow.storage import Database


class RhythmSnapshotRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(self, workspace_id: str) -> HumanStateSnapshot | None:
        async with self.database.connect() as connection:
            return await self.get_in(connection, workspace_id)

    async def get_in(
        self, connection: aiosqlite.Connection, workspace_id: str
    ) -> HumanStateSnapshot | None:
        row = await (
            await connection.execute(
                "SELECT snapshot FROM rhythm_snapshots WHERE workspace_id = ?",
                (workspace_id,),
            )
        ).fetchone()
        return self._from_row(row) if row else None

    async def save_in(self, connection: aiosqlite.Connection, snapshot: HumanStateSnapshot) -> None:
        await connection.execute(
            """
            INSERT INTO rhythm_snapshots(workspace_id, snapshot, version, updated_at)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(workspace_id) DO UPDATE SET
                snapshot = excluded.snapshot,
                version = rhythm_snapshots.version + 1,
                updated_at = excluded.updated_at
            """,
            (
                snapshot.workspace_id,
                snapshot.model_dump_json(),
                datetime.now(UTC).isoformat(),
            ),
        )

    @staticmethod
    def _from_row(row: Any) -> HumanStateSnapshot:
        return HumanStateSnapshot.model_validate_json(row["snapshot"])
