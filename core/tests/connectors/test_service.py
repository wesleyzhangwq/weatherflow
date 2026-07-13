from datetime import UTC, datetime, timedelta
from pathlib import Path

from weatherflow.connectors import (
    ComposioLink,
    ComposioRemoteAccount,
    ConnectionPhase,
    ConnectorKind,
    ConnectorRepository,
    ConnectorService,
    ConnectorSnapshot,
    SourceItem,
)
from weatherflow.events import EventLedger
from weatherflow.extensions import (
    CredentialRef,
    CredentialUnavailableError,
    KeyringCredentialStore,
)
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository

SECRET = "composio-project-secret"


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class FakeGateway:
    def __init__(self) -> None:
        self.validated: list[str] = []
        self.revoked: list[str] = []
        self.phase = ConnectionPhase.WAITING_USER

    async def validate_api_key(self, api_key: str) -> None:
        self.validated.append(api_key)

    async def create_link(self, connector: ConnectorKind, *, user_id: str) -> ComposioLink:
        return ComposioLink(
            redirect_url=f"https://connect.composio.dev/{connector.value}",
            connected_account_id=f"ca_{connector.value}",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )

    async def get_account(self, account_id: str) -> ComposioRemoteAccount:
        return ComposioRemoteAccount(
            id=account_id,
            phase=self.phase,
            toolkit="github",
            display_name="wesz",
        )

    async def revoke(self, account_id: str) -> None:
        self.revoked.append(account_id)


async def setup(tmp_path: Path):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = Workspace.new(
        name="Connections",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await WorkspaceRepository(database).create(workspace)
    repository = ConnectorRepository(database)
    keyring = FakeKeyring()
    credential_store = KeyringCredentialStore(backend=keyring)
    credential_store.set(CredentialRef(provider="composio", name="project_api_key"), SECRET)
    gateway = FakeGateway()
    service = ConnectorService(
        repository=repository,
        ledger=EventLedger(database),
        credential_store=credential_store,
        gateway=gateway,
        installation_id="wf-installation",
    )
    return database, workspace, repository, keyring, gateway, service


async def test_configure_handoff_and_authoritative_activation(tmp_path: Path) -> None:
    _, workspace, repository, keyring, gateway, service = await setup(tmp_path)
    await service.configure()

    handoff = await service.connect(workspace.id, ConnectorKind.GITHUB)
    waiting = await repository.get_attempt(handoff.attempt_id)
    assert waiting is not None and waiting.phase is ConnectionPhase.WAITING_USER
    assert await repository.get_binding(workspace.id, ConnectorKind.GITHUB) is None
    waiting_status = (await service.statuses(workspace.id))[0]
    assert waiting_status.attempt_id == handoff.attempt_id
    assert waiting_status.attempt_expires_at == handoff.expires_at

    gateway.phase = ConnectionPhase.ACTIVE
    active = await service.refresh_attempt(handoff.attempt_id)

    assert active.phase is ConnectionPhase.ACTIVE
    binding = await repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert binding is not None and binding.granted_scopes == frozenset({"github:read"})
    assert keyring.values == {("ai.weatherflow.composio", "project_api_key"): SECRET}
    events = await service.ledger.list_stream("connector", ConnectorKind.GITHUB.value, limit=20)
    serialized = "".join(event.model_dump_json() for event in events)
    assert SECRET not in serialized
    assert "connect.composio.dev" not in serialized
    assert [event.type for event in events] == [
        "connector.configuration_changed",
        "connector.handoff_started",
        "connector.activated",
    ]


async def test_unavailable_keyring_keeps_background_connectors_disabled(
    tmp_path: Path,
) -> None:
    class UnavailableStore:
        def resolve(self, reference: CredentialRef) -> str | None:
            raise CredentialUnavailableError(reference.key)

    _, _, _, _, _, service = await setup(tmp_path)
    service.credential_store = UnavailableStore()

    assert service.configured() is False


async def test_disconnect_revokes_remote_and_clears_local_derived_data(tmp_path: Path) -> None:
    _, workspace, repository, _, gateway, service = await setup(tmp_path)
    await service.configure()
    handoff = await service.connect(workspace.id, ConnectorKind.GITHUB)
    gateway.phase = ConnectionPhase.ACTIVE
    await service.refresh_attempt(handoff.attempt_id)
    now = datetime.now(UTC)
    await repository.replace_snapshot(
        ConnectorSnapshot(
            workspace_id=workspace.id,
            connector=ConnectorKind.GITHUB,
            fetched_at=now,
            expires_at=now + timedelta(hours=1),
            items=(
                SourceItem(
                    source_id="issue-1",
                    occurred_at=now,
                    title="Issue",
                    summary="Summary",
                ),
            ),
        )
    )

    await service.disconnect(ConnectorKind.GITHUB)

    assert gateway.revoked == ["ca_github"]
    assert await repository.get_account(ConnectorKind.GITHUB) is None
    assert await repository.get_binding(workspace.id, ConnectorKind.GITHUB) is None
    assert await repository.get_snapshot(workspace.id, ConnectorKind.GITHUB) is None
