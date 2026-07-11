import json
import sqlite3
from typing import Any

import aiosqlite

from weatherflow.capabilities.models import ToolSpec
from weatherflow.capabilities.snapshots import RunCapabilitySnapshot, canonical_tool
from weatherflow.storage import Database


class DuplicateCapabilitySnapshot(ValueError):
    pass


class CapabilitySnapshotRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_in(
        self,
        connection: aiosqlite.Connection,
        snapshot: RunCapabilitySnapshot,
    ) -> None:
        try:
            await connection.execute(
                """
                INSERT INTO capability_snapshots(
                    id, run_id, catalog_revision, tools, digest, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.id,
                    snapshot.run_id,
                    snapshot.catalog_revision,
                    json.dumps(
                        [canonical_tool(tool) for tool in snapshot.tools],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    snapshot.digest,
                    snapshot.created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as error:
            if "UNIQUE constraint failed" in str(error):
                raise DuplicateCapabilitySnapshot(snapshot.run_id) from error
            raise

    async def get(self, snapshot_id: str) -> RunCapabilitySnapshot | None:
        async with self.database.connect() as connection:
            return await self.get_in(connection, snapshot_id)

    async def get_in(
        self, connection: aiosqlite.Connection, snapshot_id: str
    ) -> RunCapabilitySnapshot | None:
        row = await (
            await connection.execute(
                "SELECT * FROM capability_snapshots WHERE id = ?", (snapshot_id,)
            )
        ).fetchone()
        return self._from_row(row) if row else None

    async def get_by_run_id(self, run_id: str) -> RunCapabilitySnapshot | None:
        async with self.database.connect() as connection:
            return await self.get_by_run_id_in(connection, run_id)

    async def get_by_run_id_in(
        self, connection: aiosqlite.Connection, run_id: str
    ) -> RunCapabilitySnapshot | None:
        row = await (
            await connection.execute(
                "SELECT * FROM capability_snapshots WHERE run_id = ?", (run_id,)
            )
        ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def _from_row(row: Any) -> RunCapabilitySnapshot:
        tools = tuple(ToolSpec.model_validate(value) for value in json.loads(row["tools"]))
        return RunCapabilitySnapshot.model_validate(
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "catalog_revision": row["catalog_revision"],
                "tools": tools,
                "digest": row["digest"],
                "created_at": row["created_at"],
            }
        )
