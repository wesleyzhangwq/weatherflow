import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from weatherflow.connectors import (
    ConnectionAttempt,
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
    ConnectorRepository,
    ConnectorSnapshot,
    ConversationAccess,
    SourceItem,
)
from weatherflow.extensions import CredentialRef
from weatherflow.runs import Run, RunRepository
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository


async def setup(tmp_path: Path) -> tuple[Database, Workspace]:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = Workspace.new(
        name="Connectors",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await WorkspaceRepository(database).create(workspace)
    return database, workspace


async def test_connector_state_round_trips_without_connect_url_or_secret(tmp_path: Path) -> None:
    database, workspace = await setup(tmp_path)
    repository = ConnectorRepository(database)
    now = datetime.now(UTC)
    account = ConnectorAccount.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GITHUB,
        external_account_id="ca_123",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now,
    )
    attempt = ConnectionAttempt.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GITHUB,
        account_id=account.id,
        external_account_id=account.external_account_id,
        expires_at=now + timedelta(minutes=5),
        now=now,
    )
    binding = ConnectorBinding.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GITHUB,
        account_id=account.id,
        now=now,
    )

    await repository.save_account(account)
    await repository.save_attempt(attempt)
    await repository.save_binding(binding)

    assert await repository.get_account(workspace.id, ConnectorKind.GITHUB) == account
    assert await repository.get_attempt(attempt.id) == attempt
    assert await repository.get_binding(workspace.id, ConnectorKind.GITHUB) == binding
    async with database.connect() as connection:
        durable_rows: list[str] = []
        for table in ("connector_accounts", "connection_attempts", "connector_bindings"):
            rows = await (await connection.execute(f"SELECT * FROM {table}")).fetchall()
            durable_rows.extend(str(dict(row)) for row in rows)
        dump = "\n".join(durable_rows)
    assert "https://" not in dump
    assert "secret" not in dump


async def test_snapshot_replacement_and_due_binding_query(tmp_path: Path) -> None:
    database, workspace = await setup(tmp_path)
    repository = ConnectorRepository(database)
    now = datetime.now(UTC)
    account = ConnectorAccount.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GMAIL,
        external_account_id="ca_mail",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now,
    ).activate(now=now)
    binding = ConnectorBinding.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GMAIL,
        account_id=account.id,
        now=now,
    ).model_copy(update={"next_sync_at": now - timedelta(seconds=1)})
    first = ConnectorSnapshot(
        workspace_id=workspace.id,
        connector=ConnectorKind.GMAIL,
        fetched_at=now,
        expires_at=now + timedelta(hours=1),
        items=(
            SourceItem(
                source_id="mail-1",
                occurred_at=now,
                title="First",
                summary="Unread",
            ),
        ),
    )
    second = first.model_copy(
        update={
            "fetched_at": now + timedelta(minutes=1),
            "items": (
                SourceItem(
                    source_id="mail-2",
                    occurred_at=now,
                    title="Second",
                    summary="Unread",
                ),
            ),
        }
    )

    await repository.save_account(account)
    await repository.save_binding(binding)
    await repository.replace_snapshot(first)
    await repository.replace_snapshot(second)

    assert await repository.get_snapshot(workspace.id, ConnectorKind.GMAIL) == second
    assert await repository.list_due_bindings(now) == [binding]


async def test_installation_user_id_is_stable_and_non_identifying(tmp_path: Path) -> None:
    database, _ = await setup(tmp_path)
    repository = ConnectorRepository(database)

    first = await repository.installation_user_id()
    second = await repository.installation_user_id()

    assert first == second
    assert first.startswith("wf_")
    assert "@" not in first


async def test_account_attempt_and_binding_reject_cross_workspace_identity(
    tmp_path: Path,
) -> None:
    database, first = await setup(tmp_path)
    second = Workspace.new(
        name="Second",
        action_roots=[tmp_path / "project-2"],
        internal_root=tmp_path / "internal-2",
        artifact_root=tmp_path / "artifacts-2",
    )
    await WorkspaceRepository(database).create(second)
    repository = ConnectorRepository(database)
    now = datetime.now(UTC)
    account = ConnectorAccount.new(
        workspace_id=first.id,
        connector=ConnectorKind.GITHUB,
        external_account_id="ca_first",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now,
    )
    await repository.save_account(account)

    assert await repository.get_account_by_id(second.id, account.id) is None
    with pytest.raises(sqlite3.IntegrityError):
        await repository.save_attempt(
            ConnectionAttempt.new(
                workspace_id=second.id,
                connector=ConnectorKind.GITHUB,
                account_id=account.id,
                external_account_id=account.external_account_id,
                expires_at=now + timedelta(minutes=5),
                now=now,
            )
        )
    with pytest.raises(sqlite3.IntegrityError):
        await repository.save_binding(
            ConnectorBinding.new(
                workspace_id=second.id,
                connector=ConnectorKind.GITHUB,
                account_id=account.id,
                now=now,
            )
        )
    with pytest.raises(sqlite3.IntegrityError):
        await repository.save_attempt(
            ConnectionAttempt.new(
                workspace_id=first.id,
                connector=ConnectorKind.GMAIL,
                account_id=account.id,
                external_account_id=account.external_account_id,
                expires_at=now + timedelta(minutes=5),
                now=now,
            )
        )
    with pytest.raises(sqlite3.IntegrityError):
        await repository.save_binding(
            ConnectorBinding.new(
                workspace_id=first.id,
                connector=ConnectorKind.GMAIL,
                account_id=account.id,
                now=now,
            )
        )


async def test_run_connector_route_rejects_mismatched_run_workspace(tmp_path: Path) -> None:
    database, first = await setup(tmp_path)
    second = Workspace.new(
        name="Second",
        action_roots=[tmp_path / "project-2"],
        internal_root=tmp_path / "internal-2",
        artifact_root=tmp_path / "artifacts-2",
    )
    await WorkspaceRepository(database).create(second)
    run = Run.new(
        client_request_id="cross-workspace-route",
        user_intent="inspect",
        workspace_id=first.id,
    )
    async with database.transaction() as connection:
        await RunRepository(database).create_in(connection, run)
    repository = ConnectorRepository(database)
    now = datetime.now(UTC)
    account = ConnectorAccount.new(
        workspace_id=second.id,
        connector=ConnectorKind.GITHUB,
        external_account_id="ca_second",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now,
    ).activate(now=now)
    binding = ConnectorBinding.new(
        workspace_id=second.id,
        connector=ConnectorKind.GITHUB,
        account_id=account.id,
        now=now,
    ).with_conversation_access(
        ConversationAccess.READ,
        tool_ids=frozenset({"composio.github.get_authenticated_user"}),
        now=now,
    )
    await repository.save_account(account)
    await repository.save_binding(binding)

    with pytest.raises(ValueError, match="Run does not belong to connector Workspace"):
        await repository.freeze_run_routes(
            run_id=run.id,
            workspace_id=second.id,
            bindings=[binding],
        )
    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO run_connector_routes(
                    run_id, workspace_id, connector, account_id,
                    external_account_id, conversation_grant_revision, bound_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    second.id,
                    ConnectorKind.GITHUB.value,
                    account.id,
                    account.external_account_id,
                    binding.conversation_grant_revision,
                    now.isoformat(),
                ),
            )
