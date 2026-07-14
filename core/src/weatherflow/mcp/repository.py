from __future__ import annotations

import json
from datetime import datetime

from weatherflow.mcp.management import MCPConnectionState, MCPManagedHealth
from weatherflow.storage import Database


class SQLiteMCPConnectionRepository:
    """Persist renderer-safe MCP connection state; executable data stays in the catalog."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(self, workspace_id: str, preset_id: str) -> MCPConnectionState | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT workspace_id, preset_id, preset_version, installed, enabled,
                           health, tool_ids, installed_at, checked_at
                    FROM mcp_connections WHERE workspace_id = ? AND preset_id = ?
                    """,
                    (workspace_id, preset_id),
                )
            ).fetchone()
        return self._from_row(row) if row is not None else None

    async def list_for_workspace(self, workspace_id: str) -> tuple[MCPConnectionState, ...]:
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT workspace_id, preset_id, preset_version, installed, enabled,
                           health, tool_ids, installed_at, checked_at
                    FROM mcp_connections WHERE workspace_id = ? ORDER BY preset_id
                    """,
                    (workspace_id,),
                )
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    async def save(self, state: MCPConnectionState) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO mcp_connections(
                    workspace_id, preset_id, preset_version, installed, enabled,
                    health, tool_ids, installed_at, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, preset_id) DO UPDATE SET
                    preset_version = excluded.preset_version,
                    installed = excluded.installed,
                    enabled = excluded.enabled,
                    health = excluded.health,
                    tool_ids = excluded.tool_ids,
                    installed_at = excluded.installed_at,
                    checked_at = excluded.checked_at
                """,
                (
                    state.workspace_id,
                    state.preset_id,
                    state.preset_version,
                    int(state.installed),
                    int(state.enabled),
                    state.health.value,
                    json.dumps(state.tool_ids, separators=(",", ":")),
                    self._iso(state.installed_at),
                    self._iso(state.checked_at),
                ),
            )

    @staticmethod
    def _from_row(row) -> MCPConnectionState:
        return MCPConnectionState(
            workspace_id=str(row["workspace_id"]),
            preset_id=str(row["preset_id"]),
            preset_version=str(row["preset_version"]),
            installed=bool(row["installed"]),
            enabled=bool(row["enabled"]),
            health=MCPManagedHealth(str(row["health"])),
            tool_ids=tuple(json.loads(row["tool_ids"])),
            installed_at=SQLiteMCPConnectionRepository._datetime(row["installed_at"]),
            checked_at=SQLiteMCPConnectionRepository._datetime(row["checked_at"]),
        )

    @staticmethod
    def _datetime(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value is not None else None

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None
