import sqlite3
from typing import Any

import aiosqlite

from weatherflow.storage import Database
from weatherflow.workspaces.models import Workspace


class DuplicateWorkspaceError(ValueError):
    pass


class WorkspaceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(self, workspace: Workspace) -> None:
        async with self.database.transaction() as connection:
            await self.create_in(connection, workspace)

    async def create_in(self, connection: aiosqlite.Connection, workspace: Workspace) -> None:
        try:
            await connection.execute(
                """
                INSERT INTO workspaces(id, name, config, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace.id,
                    workspace.name,
                    workspace.model_dump_json(),
                    workspace.version,
                    workspace.created_at.isoformat(),
                    workspace.updated_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as error:
            if "UNIQUE constraint failed" in str(error):
                raise DuplicateWorkspaceError(workspace.id) from error
            raise

    async def get(self, workspace_id: str) -> Workspace | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM workspaces WHERE id = ?", (workspace_id,)
                )
            ).fetchone()
        return self._from_row(row) if row else None

    async def list_all(self) -> list[Workspace]:
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute("SELECT config FROM workspaces ORDER BY created_at, id")
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: Any) -> Workspace:
        return Workspace.model_validate_json(row["config"])
