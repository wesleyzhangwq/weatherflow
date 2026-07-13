from datetime import UTC, datetime, timedelta
from pathlib import Path

from weatherflow.connectors import (
    ConnectionAttempt,
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
    ConnectorRepository,
    ConnectorSnapshot,
    SourceItem,
)
from weatherflow.extensions import CredentialRef
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

    assert await repository.get_account(ConnectorKind.GITHUB) == account
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
