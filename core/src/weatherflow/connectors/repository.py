from datetime import datetime
from typing import Any

from ulid import ULID

from weatherflow.connectors.models import (
    ConnectionAttempt,
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
    ConnectorSnapshot,
)
from weatherflow.storage import Database


class ConnectorRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def installation_user_id(self) -> str:
        async with self.database.transaction() as connection:
            row = await (
                await connection.execute(
                    "SELECT user_id FROM connector_installation WHERE singleton = 1"
                )
            ).fetchone()
            if row is not None:
                return str(row["user_id"])
            user_id = f"wf_{ULID()}"
            await connection.execute(
                "INSERT INTO connector_installation(singleton, user_id) VALUES (1, ?)",
                (user_id,),
            )
            return user_id

    async def save_account(self, account: ConnectorAccount) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO connector_accounts(
                    id, connector, external_account_id, phase, config,
                    version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connector) DO UPDATE SET
                    id = excluded.id,
                    external_account_id = excluded.external_account_id,
                    phase = excluded.phase,
                    config = excluded.config,
                    version = excluded.version,
                    updated_at = excluded.updated_at
                """,
                (
                    account.id,
                    account.connector.value,
                    account.external_account_id,
                    account.phase.value,
                    account.model_dump_json(),
                    account.version,
                    account.created_at.isoformat(),
                    account.updated_at.isoformat(),
                ),
            )

    async def get_account(self, connector: ConnectorKind) -> ConnectorAccount | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM connector_accounts WHERE connector = ?",
                    (connector.value,),
                )
            ).fetchone()
        return ConnectorAccount.model_validate_json(row["config"]) if row else None

    async def get_account_by_id(self, account_id: str) -> ConnectorAccount | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM connector_accounts WHERE id = ?", (account_id,)
                )
            ).fetchone()
        return ConnectorAccount.model_validate_json(row["config"]) if row else None

    async def delete_account(self, connector: ConnectorKind) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(
                "DELETE FROM connector_accounts WHERE connector = ?", (connector.value,)
            )

    async def delete_connector(self, connector: ConnectorKind) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(
                "DELETE FROM connector_snapshots WHERE connector = ?", (connector.value,)
            )
            await connection.execute(
                "DELETE FROM connector_accounts WHERE connector = ?", (connector.value,)
            )

    async def save_attempt(self, attempt: ConnectionAttempt) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO connection_attempts(
                    id, workspace_id, connector, account_id, phase, expires_at,
                    config, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    phase = excluded.phase,
                    config = excluded.config,
                    updated_at = excluded.updated_at
                """,
                (
                    attempt.id,
                    attempt.workspace_id,
                    attempt.connector.value,
                    attempt.account_id,
                    attempt.phase.value,
                    attempt.expires_at.isoformat(),
                    attempt.model_dump_json(),
                    attempt.created_at.isoformat(),
                    attempt.updated_at.isoformat(),
                ),
            )

    async def get_attempt(self, attempt_id: str) -> ConnectionAttempt | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM connection_attempts WHERE id = ?", (attempt_id,)
                )
            ).fetchone()
        return ConnectionAttempt.model_validate_json(row["config"]) if row else None

    async def latest_attempt(
        self, workspace_id: str, connector: ConnectorKind
    ) -> ConnectionAttempt | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT config FROM connection_attempts
                    WHERE workspace_id = ? AND connector = ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (workspace_id, connector.value),
                )
            ).fetchone()
        return ConnectionAttempt.model_validate_json(row["config"]) if row else None

    async def save_binding(self, binding: ConnectorBinding) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO connector_bindings(
                    workspace_id, connector, account_id, enabled, auto_fetch_enabled,
                    next_sync_at, config, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, connector) DO UPDATE SET
                    account_id = excluded.account_id,
                    enabled = excluded.enabled,
                    auto_fetch_enabled = excluded.auto_fetch_enabled,
                    next_sync_at = excluded.next_sync_at,
                    config = excluded.config,
                    version = excluded.version,
                    updated_at = excluded.updated_at
                """,
                (
                    binding.workspace_id,
                    binding.connector.value,
                    binding.account_id,
                    int(binding.enabled),
                    int(binding.auto_fetch_enabled),
                    binding.next_sync_at.isoformat(),
                    binding.model_dump_json(),
                    binding.version,
                    binding.created_at.isoformat(),
                    binding.updated_at.isoformat(),
                ),
            )

    async def get_binding(
        self, workspace_id: str, connector: ConnectorKind
    ) -> ConnectorBinding | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT config FROM connector_bindings
                    WHERE workspace_id = ? AND connector = ?
                    """,
                    (workspace_id, connector.value),
                )
            ).fetchone()
        return ConnectorBinding.model_validate_json(row["config"]) if row else None

    async def list_bindings(self, workspace_id: str) -> list[ConnectorBinding]:
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT config FROM connector_bindings
                    WHERE workspace_id = ? ORDER BY connector
                    """,
                    (workspace_id,),
                )
            ).fetchall()
        return [ConnectorBinding.model_validate_json(row["config"]) for row in rows]

    async def list_due_bindings(self, now: datetime) -> list[ConnectorBinding]:
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT config FROM connector_bindings
                    WHERE enabled = 1 AND auto_fetch_enabled = 1 AND next_sync_at <= ?
                    ORDER BY next_sync_at, workspace_id, connector
                    """,
                    (now.isoformat(),),
                )
            ).fetchall()
        return [ConnectorBinding.model_validate_json(row["config"]) for row in rows]

    async def delete_binding(self, workspace_id: str, connector: ConnectorKind) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(
                "DELETE FROM connector_bindings WHERE workspace_id = ? AND connector = ?",
                (workspace_id, connector.value),
            )

    async def replace_snapshot(self, snapshot: ConnectorSnapshot) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO connector_snapshots(workspace_id, connector, fetched_at, snapshot)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(workspace_id, connector) DO UPDATE SET
                    fetched_at = excluded.fetched_at,
                    snapshot = excluded.snapshot
                """,
                (
                    snapshot.workspace_id,
                    snapshot.connector.value,
                    snapshot.fetched_at.isoformat(),
                    snapshot.model_dump_json(),
                ),
            )

    async def get_snapshot(
        self, workspace_id: str, connector: ConnectorKind
    ) -> ConnectorSnapshot | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT snapshot FROM connector_snapshots
                    WHERE workspace_id = ? AND connector = ?
                    """,
                    (workspace_id, connector.value),
                )
            ).fetchone()
        return ConnectorSnapshot.model_validate_json(row["snapshot"]) if row else None

    async def delete_snapshot(self, workspace_id: str, connector: ConnectorKind) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(
                "DELETE FROM connector_snapshots WHERE workspace_id = ? AND connector = ?",
                (workspace_id, connector.value),
            )

    @staticmethod
    def _from_row(row: Any) -> ConnectorAccount:
        return ConnectorAccount.model_validate_json(row["config"])
