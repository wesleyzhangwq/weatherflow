import json
from datetime import UTC, datetime
from typing import Any

from ulid import ULID

from weatherflow.connectors.models import (
    ConnectionAttempt,
    ConnectionPhase,
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
    ConnectorSnapshot,
    RunConnectorRoute,
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
            cursor = await connection.execute(
                """
                INSERT INTO connector_accounts(
                    id, workspace_id, connector, external_account_id, phase, config,
                    version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    external_account_id = excluded.external_account_id,
                    phase = excluded.phase,
                    config = excluded.config,
                    version = excluded.version,
                    updated_at = excluded.updated_at
                WHERE connector_accounts.workspace_id = excluded.workspace_id
                  AND connector_accounts.connector = excluded.connector
                """,
                (
                    account.id,
                    account.workspace_id,
                    account.connector.value,
                    account.external_account_id,
                    account.phase.value,
                    account.model_dump_json(),
                    account.version,
                    account.created_at.isoformat(),
                    account.updated_at.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("connector account identity cannot change workspace or provider")

    async def get_account(
        self, workspace_id: str, connector: ConnectorKind
    ) -> ConnectorAccount | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT account.config
                    FROM connector_accounts AS account
                    LEFT JOIN connector_bindings AS binding
                      ON binding.workspace_id = account.workspace_id
                     AND binding.connector = account.connector
                     AND binding.account_id = account.id
                    WHERE account.workspace_id = ? AND account.connector = ?
                    ORDER BY
                        CASE WHEN binding.account_id IS NULL THEN 1 ELSE 0 END,
                        account.updated_at DESC,
                        account.id DESC
                    LIMIT 1
                    """,
                    (workspace_id, connector.value),
                )
            ).fetchone()
        return ConnectorAccount.model_validate_json(row["config"]) if row else None

    async def get_account_by_id(
        self, workspace_id: str, account_id: str
    ) -> ConnectorAccount | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT config FROM connector_accounts
                    WHERE workspace_id = ? AND id = ?
                    """,
                    (workspace_id, account_id),
                )
            ).fetchone()
        return ConnectorAccount.model_validate_json(row["config"]) if row else None

    async def delete_account(self, workspace_id: str, account_id: str) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(
                "DELETE FROM connector_accounts WHERE workspace_id = ? AND id = ?",
                (workspace_id, account_id),
            )

    async def delete_connector(self, workspace_id: str, connector: ConnectorKind) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(
                "DELETE FROM connector_snapshots WHERE workspace_id = ? AND connector = ?",
                (workspace_id, connector.value),
            )
            await connection.execute(
                "DELETE FROM connector_accounts WHERE workspace_id = ? AND connector = ?",
                (workspace_id, connector.value),
            )

    async def save_attempt(self, attempt: ConnectionAttempt) -> None:
        async with self.database.transaction() as connection:
            waiting_rows = await (
                await connection.execute(
                    """
                    SELECT config FROM connection_attempts
                    WHERE workspace_id = ? AND connector = ? AND phase = ? AND id != ?
                    """,
                    (
                        attempt.workspace_id,
                        attempt.connector.value,
                        ConnectionPhase.WAITING_USER.value,
                        attempt.id,
                    ),
                )
            ).fetchall()
            for row in waiting_rows:
                waiting = ConnectionAttempt.model_validate_json(row["config"])
                expired = waiting.with_phase(ConnectionPhase.EXPIRED)
                await connection.execute(
                    """
                    UPDATE connection_attempts
                    SET phase = ?, config = ?, updated_at = ?
                    WHERE id = ? AND workspace_id = ? AND phase = ?
                    """,
                    (
                        expired.phase.value,
                        expired.model_dump_json(),
                        expired.updated_at.isoformat(),
                        expired.id,
                        expired.workspace_id,
                        ConnectionPhase.WAITING_USER.value,
                    ),
                )
            cursor = await connection.execute(
                """
                INSERT INTO connection_attempts(
                    id, workspace_id, connector, account_id, phase, expires_at,
                    config, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    phase = excluded.phase,
                    config = excluded.config,
                    updated_at = excluded.updated_at
                WHERE connection_attempts.workspace_id = excluded.workspace_id
                  AND connection_attempts.connector = excluded.connector
                  AND connection_attempts.account_id = excluded.account_id
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
            if cursor.rowcount != 1:
                raise ValueError("connection attempt identity is immutable")

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
                    ORDER BY created_at DESC, id DESC LIMIT 1
                    """,
                    (workspace_id, connector.value),
                )
            ).fetchone()
        return ConnectionAttempt.model_validate_json(row["config"]) if row else None

    async def finalize_attempt(
        self,
        attempt_id: str,
        *,
        phase: ConnectionPhase,
        display_name: str | None = None,
        now: datetime | None = None,
    ) -> tuple[ConnectionAttempt, ConnectorBinding | None, bool]:
        if phase not in {
            ConnectionPhase.ACTIVE,
            ConnectionPhase.ERROR,
            ConnectionPhase.EXPIRED,
            ConnectionPhase.REVOKED,
        }:
            raise ValueError(f"unsupported terminal connection phase: {phase.value}")
        observed = now or datetime.now(UTC)
        async with self.database.transaction() as connection:
            attempt_row = await (
                await connection.execute(
                    "SELECT config FROM connection_attempts WHERE id = ?",
                    (attempt_id,),
                )
            ).fetchone()
            if attempt_row is None:
                raise LookupError(attempt_id)
            attempt = ConnectionAttempt.model_validate_json(attempt_row["config"])
            if attempt.phase is not ConnectionPhase.WAITING_USER:
                return attempt, None, False
            target_phase = (
                ConnectionPhase.EXPIRED
                if phase is ConnectionPhase.ACTIVE and attempt.expires_at <= observed
                else phase
            )
            updated_attempt = attempt.with_phase(target_phase, now=observed)
            account_row = await (
                await connection.execute(
                    """
                    SELECT config FROM connector_accounts
                    WHERE workspace_id = ? AND id = ? AND connector = ?
                    """,
                    (attempt.workspace_id, attempt.account_id, attempt.connector.value),
                )
            ).fetchone()
            if account_row is None:
                raise LookupError(attempt.account_id)
            account = ConnectorAccount.model_validate_json(account_row["config"])
            if account.external_account_id != attempt.external_account_id:
                raise ValueError("connection attempt account identity changed")

            binding: ConnectorBinding | None = None
            if target_phase is ConnectionPhase.ACTIVE:
                active = account.activate(now=observed, display_name=display_name)
                previous_row = await (
                    await connection.execute(
                        """
                        SELECT config FROM connector_bindings
                        WHERE workspace_id = ? AND connector = ?
                        """,
                        (attempt.workspace_id, attempt.connector.value),
                    )
                ).fetchone()
                previous = (
                    ConnectorBinding.model_validate_json(previous_row["config"])
                    if previous_row
                    else None
                )
                binding = ConnectorBinding.new(
                    workspace_id=attempt.workspace_id,
                    connector=attempt.connector,
                    account_id=account.id,
                    now=observed,
                )
                if previous is not None:
                    binding = binding.model_copy(
                        update={
                            "auto_fetch_enabled": previous.auto_fetch_enabled,
                            "interval_minutes": previous.interval_minutes,
                        }
                    )
                await self._save_account(connection, active)
                await self._save_binding(connection, binding)
            else:
                await self._save_account(
                    connection,
                    account.with_phase(target_phase, now=observed),
                )
            cursor = await connection.execute(
                """
                UPDATE connection_attempts
                SET phase = ?, config = ?, updated_at = ?
                WHERE id = ? AND workspace_id = ? AND connector = ?
                  AND account_id = ? AND phase = ?
                """,
                (
                    updated_attempt.phase.value,
                    updated_attempt.model_dump_json(),
                    updated_attempt.updated_at.isoformat(),
                    updated_attempt.id,
                    updated_attempt.workspace_id,
                    updated_attempt.connector.value,
                    updated_attempt.account_id,
                    ConnectionPhase.WAITING_USER.value,
                ),
            )
            if cursor.rowcount != 1:
                current = await (
                    await connection.execute(
                        "SELECT config FROM connection_attempts WHERE id = ?",
                        (attempt_id,),
                    )
                ).fetchone()
                if current is None:
                    raise LookupError(attempt_id)
                return ConnectionAttempt.model_validate_json(current["config"]), None, False
            return updated_attempt, binding, True

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

    async def count_bindings_for_account(self, account_id: str) -> int:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT COUNT(*) AS total FROM connector_bindings WHERE account_id = ?",
                    (account_id,),
                )
            ).fetchone()
        return int(row["total"]) if row else 0

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

    async def freeze_run_routes(
        self,
        *,
        run_id: str,
        workspace_id: str,
        bindings: list[ConnectorBinding],
    ) -> tuple[RunConnectorRoute, ...]:
        routes: list[RunConnectorRoute] = []
        async with self.database.transaction() as connection:
            run_row = await (
                await connection.execute(
                    "SELECT workspace_id FROM runs WHERE id = ?",
                    (run_id,),
                )
            ).fetchone()
            if run_row is None or str(run_row["workspace_id"]) != workspace_id:
                raise ValueError("Run does not belong to connector Workspace")
            existing = await (
                await connection.execute(
                    "SELECT * FROM run_connector_routes WHERE run_id = ? ORDER BY connector",
                    (run_id,),
                )
            ).fetchall()
            if existing:
                return tuple(self._route_from_row(row) for row in existing)
            for binding in bindings:
                if (
                    binding.workspace_id != workspace_id
                    or not binding.enabled
                    or not binding.conversation_tool_ids
                ):
                    continue
                account_row = await (
                    await connection.execute(
                        """
                        SELECT config FROM connector_accounts
                        WHERE workspace_id = ? AND id = ?
                        """,
                        (workspace_id, binding.account_id),
                    )
                ).fetchone()
                if account_row is None:
                    continue
                account = ConnectorAccount.model_validate_json(account_row["config"])
                if account.connector is not binding.connector or account.phase.value != "active":
                    continue
                route = RunConnectorRoute(
                    run_id=run_id,
                    workspace_id=workspace_id,
                    connector=binding.connector,
                    account_id=account.id,
                    external_account_id=account.external_account_id,
                    conversation_grant_revision=binding.conversation_grant_revision,
                    bound_at=datetime.now().astimezone(),
                )
                await connection.execute(
                    """
                    INSERT INTO run_connector_routes(
                        run_id, workspace_id, connector, account_id,
                        external_account_id, conversation_grant_revision, bound_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        route.run_id,
                        route.workspace_id,
                        route.connector.value,
                        route.account_id,
                        route.external_account_id,
                        route.conversation_grant_revision,
                        route.bound_at.isoformat(),
                    ),
                )
                routes.append(route)
        return tuple(routes)

    async def get_run_route(
        self, run_id: str, connector: ConnectorKind
    ) -> RunConnectorRoute | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT * FROM run_connector_routes
                    WHERE run_id = ? AND connector = ?
                    """,
                    (run_id, connector.value),
                )
            ).fetchone()
        return self._route_from_row(row) if row else None

    async def clone_run_routes(
        self,
        *,
        parent_run_id: str,
        child_run_id: str,
        workspace_id: str,
    ) -> tuple[RunConnectorRoute, ...]:
        from weatherflow.capabilities import ToolEffect, ToolSpec
        from weatherflow.connectors.tools import COMPOSIO_TOOLS_BY_ID

        cloned: list[RunConnectorRoute] = []
        async with self.database.transaction() as connection:
            run_rows = await (
                await connection.execute(
                    """
                    SELECT id, workspace_id FROM runs
                    WHERE id IN (?, ?)
                    """,
                    (parent_run_id, child_run_id),
                )
            ).fetchall()
            ownership = {str(row["id"]): str(row["workspace_id"]) for row in run_rows}
            if ownership != {
                parent_run_id: workspace_id,
                child_run_id: workspace_id,
            }:
                raise ValueError("Worker connector routes must stay in the parent Workspace")
            snapshot_row = await (
                await connection.execute(
                    "SELECT tools FROM capability_snapshots WHERE run_id = ?",
                    (child_run_id,),
                )
            ).fetchone()
            if snapshot_row is None:
                raise LookupError(f"child Run has no capability snapshot: {child_run_id}")
            child_tools = tuple(
                ToolSpec.model_validate(value) for value in json.loads(snapshot_row["tools"])
            )
            definitions_by_connector: dict[ConnectorKind, list[Any]] = {}
            for tool in child_tools:
                definition = COMPOSIO_TOOLS_BY_ID.get(tool.tool_id)
                if definition is None:
                    continue
                if definition.effect is not ToolEffect.NETWORK_READ:
                    raise PermissionError("Workers may inherit only read-only connector tools")
                definitions_by_connector.setdefault(definition.connector, []).append(definition)

            for connector, definitions in sorted(
                definitions_by_connector.items(), key=lambda item: item[0].value
            ):
                parent_row = await (
                    await connection.execute(
                        """
                        SELECT * FROM run_connector_routes
                        WHERE run_id = ? AND workspace_id = ? AND connector = ?
                        """,
                        (parent_run_id, workspace_id, connector.value),
                    )
                ).fetchone()
                if parent_row is None:
                    raise PermissionError("parent Run has no frozen connector identity")
                parent_route = self._route_from_row(parent_row)
                binding_row = await (
                    await connection.execute(
                        """
                        SELECT config FROM connector_bindings
                        WHERE workspace_id = ? AND connector = ?
                        """,
                        (workspace_id, connector.value),
                    )
                ).fetchone()
                account_row = await (
                    await connection.execute(
                        """
                        SELECT config FROM connector_accounts
                        WHERE workspace_id = ? AND id = ? AND connector = ?
                        """,
                        (workspace_id, parent_route.account_id, connector.value),
                    )
                ).fetchone()
                if binding_row is None or account_row is None:
                    raise PermissionError("connector identity is no longer active")
                binding = ConnectorBinding.model_validate_json(binding_row["config"])
                account = ConnectorAccount.model_validate_json(account_row["config"])
                tool_ids = {definition.tool_id for definition in definitions}
                required_scopes = {definition.required_scope for definition in definitions}
                if (
                    not binding.enabled
                    or account.phase is not ConnectionPhase.ACTIVE
                    or binding.account_id != parent_route.account_id
                    or account.external_account_id != parent_route.external_account_id
                    or binding.conversation_grant_revision
                    != parent_route.conversation_grant_revision
                    or not tool_ids.issubset(binding.conversation_tool_ids)
                    or not required_scopes.issubset(binding.granted_scopes)
                ):
                    raise PermissionError("connector identity or conversation grant changed")
                route = parent_route.model_copy(
                    update={
                        "run_id": child_run_id,
                        "bound_at": datetime.now(UTC),
                    }
                )
                await connection.execute(
                    """
                    INSERT INTO run_connector_routes(
                        run_id, workspace_id, connector, account_id,
                        external_account_id, conversation_grant_revision, bound_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, connector) DO NOTHING
                    """,
                    (
                        route.run_id,
                        route.workspace_id,
                        route.connector.value,
                        route.account_id,
                        route.external_account_id,
                        route.conversation_grant_revision,
                        route.bound_at.isoformat(),
                    ),
                )
                stored_row = await (
                    await connection.execute(
                        """
                        SELECT * FROM run_connector_routes
                        WHERE run_id = ? AND connector = ?
                        """,
                        (child_run_id, connector.value),
                    )
                ).fetchone()
                if stored_row is None:
                    raise RuntimeError("child connector route was not persisted")
                stored = self._route_from_row(stored_row)
                if (
                    stored.workspace_id != route.workspace_id
                    or stored.account_id != route.account_id
                    or stored.external_account_id != route.external_account_id
                    or stored.conversation_grant_revision != route.conversation_grant_revision
                ):
                    raise PermissionError("child connector route conflicts with parent identity")
                cloned.append(stored)
        return tuple(cloned)

    @staticmethod
    def _from_row(row: Any) -> ConnectorAccount:
        return ConnectorAccount.model_validate_json(row["config"])

    @staticmethod
    def _route_from_row(row: Any) -> RunConnectorRoute:
        return RunConnectorRoute(
            run_id=str(row["run_id"]),
            workspace_id=str(row["workspace_id"]),
            connector=ConnectorKind(str(row["connector"])),
            account_id=str(row["account_id"]),
            external_account_id=str(row["external_account_id"]),
            conversation_grant_revision=int(row["conversation_grant_revision"]),
            bound_at=datetime.fromisoformat(str(row["bound_at"])),
        )

    @staticmethod
    async def _save_account(connection: Any, account: ConnectorAccount) -> None:
        cursor = await connection.execute(
            """
            INSERT INTO connector_accounts(
                id, workspace_id, connector, external_account_id, phase, config,
                version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                external_account_id = excluded.external_account_id,
                phase = excluded.phase,
                config = excluded.config,
                version = excluded.version,
                updated_at = excluded.updated_at
            WHERE connector_accounts.workspace_id = excluded.workspace_id
              AND connector_accounts.connector = excluded.connector
            """,
            (
                account.id,
                account.workspace_id,
                account.connector.value,
                account.external_account_id,
                account.phase.value,
                account.model_dump_json(),
                account.version,
                account.created_at.isoformat(),
                account.updated_at.isoformat(),
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("connector account identity cannot change workspace or provider")

    @staticmethod
    async def _save_binding(connection: Any, binding: ConnectorBinding) -> None:
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
