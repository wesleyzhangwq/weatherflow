from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from weatherflow.connectors import (
    ComposioErrorCode,
    ComposioGatewayError,
    ComposioLink,
    ComposioRemoteAccount,
    ConnectionPhase,
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
    ConnectorRepository,
    ConnectorService,
    ConnectorSnapshot,
    OAuthSetup,
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
        self.oauth_failure: ConnectorKind | None = None
        self.oauth_calls: list[ConnectorKind] = []
        self.allowlist_calls: list[tuple[ConnectorKind, str, str]] = []

    async def validate_api_key(self, api_key: str) -> None:
        self.validated.append(api_key)

    async def oauth_setup(self, connector: ConnectorKind) -> OAuthSetup:
        self.oauth_calls.append(connector)
        if connector is self.oauth_failure:
            raise ComposioGatewayError(ComposioErrorCode.TRANSPORT, retryable=True)
        if connector is ConnectorKind.GOOGLE_CALENDAR:
            return OAuthSetup.BRING_YOUR_OWN
        return OAuthSetup.MANAGED

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

    async def ensure_action_allowlist(
        self,
        connector: ConnectorKind,
        *,
        connected_account_id: str,
        user_id: str,
    ) -> None:
        self.allowlist_calls.append((connector, connected_account_id, user_id))


class UniqueLinkGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self._next_link = 0
        self.phases: dict[str, ConnectionPhase] = {}

    async def create_link(self, connector: ConnectorKind, *, user_id: str) -> ComposioLink:
        self._next_link += 1
        account_id = f"ca_{connector.value}_{self._next_link}"
        self.phases[account_id] = ConnectionPhase.WAITING_USER
        return ComposioLink(
            redirect_url=f"https://connect.composio.dev/{account_id}",
            connected_account_id=account_id,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )

    async def get_account(self, account_id: str) -> ComposioRemoteAccount:
        return ComposioRemoteAccount(
            id=account_id,
            phase=self.phases[account_id],
            toolkit="github",
            display_name=account_id,
        )


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
    assert binding is not None and binding.granted_scopes == frozenset(
        {"github:read", "github:write"}
    )
    assert gateway.allowlist_calls == [(ConnectorKind.GITHUB, "ca_github", "wf-installation")]
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


async def test_same_connector_accounts_are_isolated_by_workspace(tmp_path: Path) -> None:
    database, first, repository, _, _, service = await setup(tmp_path)
    second = Workspace.new(
        name="Second connection boundary",
        action_roots=[tmp_path / "project-2"],
        internal_root=tmp_path / "internal-2",
        artifact_root=tmp_path / "artifacts-2",
    )
    await WorkspaceRepository(database).create(second)
    gateway = UniqueLinkGateway()
    service.gateway = gateway

    first_handoff = await service.connect(first.id, ConnectorKind.GITHUB)
    second_handoff = await service.connect(second.id, ConnectorKind.GITHUB)
    gateway.phases["ca_github_1"] = ConnectionPhase.ACTIVE
    await service.refresh_attempt(first_handoff.attempt_id)

    first_binding = await repository.get_binding(first.id, ConnectorKind.GITHUB)
    assert first_binding is not None
    assert await repository.get_binding(second.id, ConnectorKind.GITHUB) is None

    gateway.phases["ca_github_2"] = ConnectionPhase.ACTIVE
    await service.refresh_attempt(second_handoff.attempt_id)

    second_binding = await repository.get_binding(second.id, ConnectorKind.GITHUB)
    assert second_binding is not None
    assert second_binding.account_id != first_binding.account_id
    first_account = await repository.get_account_by_id(first.id, first_binding.account_id)
    second_account = await repository.get_account_by_id(second.id, second_binding.account_id)
    assert first_account is not None
    assert second_account is not None
    assert first_account.workspace_id == first.id
    assert first_account.external_account_id == "ca_github_1"
    assert second_account.workspace_id == second.id
    assert second_account.external_account_id == "ca_github_2"
    assert await repository.get_account_by_id(first.id, second_binding.account_id) is None


async def test_only_latest_concurrent_connect_attempt_may_activate(tmp_path: Path) -> None:
    _, workspace, repository, _, _, service = await setup(tmp_path)
    gateway = UniqueLinkGateway()
    service.gateway = gateway

    first = await service.connect(workspace.id, ConnectorKind.GITHUB)
    second = await service.connect(workspace.id, ConnectorKind.GITHUB)
    gateway.phases["ca_github_1"] = ConnectionPhase.ACTIVE

    stale = await service.refresh_attempt(first.attempt_id)

    assert stale.phase is ConnectionPhase.EXPIRED
    assert await repository.get_binding(workspace.id, ConnectorKind.GITHUB) is None

    gateway.phases["ca_github_2"] = ConnectionPhase.ACTIVE
    active = await service.refresh_attempt(second.attempt_id)

    assert active.phase is ConnectionPhase.ACTIVE
    binding = await repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert binding is not None
    account = await repository.get_account_by_id(workspace.id, binding.account_id)
    assert account is not None
    assert account.external_account_id == "ca_github_2"


async def test_unavailable_keyring_keeps_background_connectors_disabled(
    tmp_path: Path,
) -> None:
    class UnavailableStore:
        def resolve(self, reference: CredentialRef) -> str | None:
            raise CredentialUnavailableError(reference.key)

    _, _, _, _, _, service = await setup(tmp_path)
    service.credential_store = UnavailableStore()

    assert service.configured() is False


async def test_statuses_expose_oauth_catalog_capabilities_without_virtual_tools(
    tmp_path: Path,
) -> None:
    _, workspace, _, _, _, service = await setup(tmp_path)

    statuses = {status.connector: status for status in await service.statuses(workspace.id)}

    assert len(statuses) == 20
    github = statuses[ConnectorKind.GITHUB]
    assert github.category == "development"
    assert github.toolkit == "github"
    assert github.auto_fetch_supported is True
    assert github.conversation_tools_supported is True
    assert len(github.available_tool_ids) == 9
    assert github.oauth_setup is OAuthSetup.MANAGED
    slack = statuses[ConnectorKind.SLACK]
    assert slack.category == "communication"
    assert slack.toolkit == "slack"
    assert slack.auto_fetch_supported is False
    assert slack.conversation_tools_supported is False
    assert slack.available_tool_ids == ()
    assert slack.oauth_setup is OAuthSetup.MANAGED
    assert statuses[ConnectorKind.GOOGLE_CALENDAR].oauth_setup is OAuthSetup.BRING_YOUR_OWN
    assert len(statuses[ConnectorKind.GMAIL].available_tool_ids) == 3
    assert len(statuses[ConnectorKind.GOOGLE_CALENDAR].available_tool_ids) == 5
    assert statuses[ConnectorKind.TRELLO].oauth_setup is OAuthSetup.UNKNOWN


async def test_one_toolkit_lookup_failure_does_not_fail_the_oauth_catalog(
    tmp_path: Path,
) -> None:
    _, workspace, _, _, gateway, service = await setup(tmp_path)
    gateway.oauth_failure = ConnectorKind.SLACK

    statuses = {status.connector: status for status in await service.statuses(workspace.id)}

    assert statuses[ConnectorKind.SLACK].oauth_setup is OAuthSetup.UNKNOWN
    assert statuses[ConnectorKind.GITHUB].oauth_setup is OAuthSetup.MANAGED

    call_count = len(gateway.oauth_calls)
    cached = {status.connector: status for status in await service.statuses(workspace.id)}

    assert len(gateway.oauth_calls) == call_count
    assert cached[ConnectorKind.SLACK].oauth_setup is OAuthSetup.UNKNOWN


async def test_successful_broker_configuration_invalidates_oauth_setup_cache(
    tmp_path: Path,
) -> None:
    _, workspace, _, _, gateway, service = await setup(tmp_path)
    await service.statuses(workspace.id)
    call_count = len(gateway.oauth_calls)

    await service.configure()
    await service.statuses(workspace.id)

    assert len(gateway.oauth_calls) == call_count * 2


async def test_unsupported_connector_cannot_enable_fetch(
    tmp_path: Path,
) -> None:
    _, workspace, repository, _, _, service = await setup(tmp_path)
    account = ConnectorAccount.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.SLACK,
        external_account_id="ca_slack",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
    )
    await repository.save_account(account)
    binding = ConnectorBinding.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.SLACK,
        account_id=account.id,
    )
    await repository.save_binding(binding)

    assert binding.auto_fetch_enabled is False
    with pytest.raises(PermissionError):
        await service.update_settings(
            workspace.id,
            ConnectorKind.SLACK,
            auto_fetch_enabled=True,
            interval_minutes=60,
        )


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

    await service.disconnect(workspace.id, ConnectorKind.GITHUB)

    assert gateway.revoked == ["ca_github"]
    assert await repository.get_account(workspace.id, ConnectorKind.GITHUB) is None
    assert await repository.get_binding(workspace.id, ConnectorKind.GITHUB) is None
    assert await repository.get_snapshot(workspace.id, ConnectorKind.GITHUB) is None
