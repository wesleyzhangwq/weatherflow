import asyncio
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
    ConnectorSyncService,
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
        self.account_error: ComposioGatewayError | None = None
        self.validation_error: Exception | None = None

    async def validate_api_key(self, api_key: str) -> None:
        if self.validation_error is not None:
            raise self.validation_error
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
        if self.account_error is not None:
            raise self.account_error
        return ComposioRemoteAccount(
            id=account_id,
            phase=self.phase,
            toolkit="github",
            display_name="wesz",
            user_id="wf-installation",
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
            user_id="wf-installation",
        )


class BlockingOldKeyGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute_read_action(self, **_kwargs):
        self.started.set()
        await self.release.wait()
        raise ComposioGatewayError(ComposioErrorCode.BROKER_AUTH)


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


async def persist_active_binding(
    repository: ConnectorRepository,
    *,
    workspace_id: str,
    error_code: str | None,
    now: datetime,
) -> tuple[ConnectorAccount, ConnectorBinding]:
    account = ConnectorAccount.new(
        workspace_id=workspace_id,
        connector=ConnectorKind.GITHUB,
        external_account_id="ca_github",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now - timedelta(hours=2),
    ).activate(now=now - timedelta(hours=2), display_name="wesz")
    await repository.save_account(account)
    binding = ConnectorBinding.new(
        workspace_id=workspace_id,
        connector=ConnectorKind.GITHUB,
        account_id=account.id,
        now=now - timedelta(hours=2),
    ).after_sync(now=now - timedelta(minutes=10), error_code=error_code)
    await repository.save_binding(binding)
    return account, binding


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


async def test_configure_upgrades_existing_active_binding_action_allowlist(
    tmp_path: Path,
) -> None:
    _, workspace, repository, _, gateway, service = await setup(tmp_path)
    await persist_active_binding(
        repository,
        workspace_id=workspace.id,
        error_code=None,
        now=datetime.now(UTC),
    )
    gateway.phase = ConnectionPhase.ACTIVE

    await service.configure()

    assert gateway.allowlist_calls == [(ConnectorKind.GITHUB, "ca_github", "wf-installation")]


async def test_startup_revalidation_cannot_overwrite_concurrent_settings_change(
    tmp_path: Path,
) -> None:
    _, workspace, repository, _, gateway, service = await setup(tmp_path)
    await persist_active_binding(
        repository,
        workspace_id=workspace.id,
        error_code=None,
        now=datetime.now(UTC),
    )
    gateway.phase = ConnectionPhase.ACTIVE
    revalidation_started = asyncio.Event()
    release_revalidation = asyncio.Event()
    original_get_account = gateway.get_account

    async def blocked_get_account(account_id: str) -> ComposioRemoteAccount:
        revalidation_started.set()
        await release_revalidation.wait()
        return await original_get_account(account_id)

    gateway.get_account = blocked_get_account  # type: ignore[method-assign]

    configure = asyncio.create_task(service.configure())
    await revalidation_started.wait()
    settings = await service.update_settings(
        workspace.id,
        ConnectorKind.GITHUB,
        auto_fetch_enabled=False,
        interval_minutes=1440,
    )
    release_revalidation.set()
    await configure

    current = await repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert current == settings
    assert current.auto_fetch_enabled is False


async def test_refresh_rejects_connected_account_owned_by_another_installation(
    tmp_path: Path,
) -> None:
    _, workspace, repository, _, gateway, service = await setup(tmp_path)
    await service.configure()
    handoff = await service.connect(workspace.id, ConnectorKind.GITHUB)
    gateway.phase = ConnectionPhase.ACTIVE
    original_get_account = gateway.get_account

    async def get_other_installation_account(account_id: str) -> ComposioRemoteAccount:
        remote = await original_get_account(account_id)
        return remote.model_copy(update={"user_id": "wf-another-installation"})

    gateway.get_account = get_other_installation_account

    refreshed = await service.refresh_attempt(handoff.attempt_id)

    assert refreshed.phase is ConnectionPhase.ERROR
    assert await repository.get_binding(workspace.id, ConnectorKind.GITHUB) is None
    assert gateway.allowlist_calls == []


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


async def test_startup_reconciliation_retries_after_native_credential_resolver_recovers(
    tmp_path: Path,
) -> None:
    _, _, _, _, gateway, service = await setup(tmp_path)
    original_resolve = service.credential_store.resolve
    calls = 0

    def flaky_resolve(reference: CredentialRef) -> str | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CredentialUnavailableError(reference.key)
        return original_resolve(reference)

    service.credential_store.resolve = flaky_resolve  # type: ignore[method-assign]

    assert await service.reconcile_configuration() is False
    assert await service.reconcile_configuration() is True
    assert await service.reconcile_configuration() is True
    assert gateway.validated == [SECRET]


async def test_startup_reconciliation_records_current_project_key_permission_failure(
    tmp_path: Path,
) -> None:
    _, workspace, repository, _, gateway, service = await setup(tmp_path)
    now = datetime.now(UTC)
    await persist_active_binding(
        repository,
        workspace_id=workspace.id,
        error_code=ComposioErrorCode.BROKER_AUTH.value,
        now=now,
    )
    gateway.validation_error = ComposioGatewayError(ComposioErrorCode.BROKER_PERMISSION)

    assert await service.reconcile_configuration() is False

    binding = await repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert binding is not None
    assert binding.last_error_code == ComposioErrorCode.BROKER_PERMISSION.value


async def test_successful_broker_configuration_clears_only_credential_errors_and_retries_now(
    tmp_path: Path,
) -> None:
    _, workspace, repository, _, gateway, service = await setup(tmp_path)
    now = datetime.now(UTC)
    gateway.phase = ConnectionPhase.ACTIVE
    await persist_active_binding(
        repository,
        workspace_id=workspace.id,
        error_code=ComposioErrorCode.BROKER_AUTH.value,
        now=now,
    )

    await service.configure()

    refreshed = await repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    account = await repository.get_account(workspace.id, ConnectorKind.GITHUB)
    assert refreshed is not None
    assert refreshed.last_error_code is None
    assert refreshed.next_sync_at >= now
    assert refreshed.next_sync_at <= datetime.now(UTC)
    assert refreshed.enabled is True
    assert account is not None and account.phase is ConnectionPhase.ACTIVE

    failed_again = refreshed.after_sync(
        now=datetime.now(UTC),
        error_code=ComposioErrorCode.AUTH.value,
    )
    await repository.save_binding(failed_again)

    await service.configure()

    provider_error = await repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert provider_error is not None
    assert provider_error.last_error_code == ComposioErrorCode.AUTH.value


async def test_new_broker_project_marks_old_accounts_for_reconnect_without_remote_revoke(
    tmp_path: Path,
) -> None:
    _, workspace, repository, _, gateway, service = await setup(tmp_path)
    now = datetime.now(UTC)
    account, _ = await persist_active_binding(
        repository,
        workspace_id=workspace.id,
        error_code=ComposioErrorCode.BROKER_AUTH.value,
        now=now,
    )
    await repository.replace_snapshot(
        ConnectorSnapshot(
            workspace_id=workspace.id,
            connector=ConnectorKind.GITHUB,
            fetched_at=now,
            expires_at=now + timedelta(hours=1),
            items=(
                SourceItem(
                    source_id="old-project-item",
                    occurred_at=now,
                    title="Old project",
                    summary="Must not survive broker project rotation",
                ),
            ),
        )
    )
    gateway.account_error = ComposioGatewayError(ComposioErrorCode.NOT_FOUND)

    await service.configure()

    refreshed_account = await repository.get_account_by_id(workspace.id, account.id)
    refreshed_binding = await repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert refreshed_account is not None
    assert refreshed_account.phase is ConnectionPhase.ERROR
    assert refreshed_binding is not None
    assert refreshed_binding.enabled is False
    assert refreshed_binding.last_error_code == "project_changed"
    assert await repository.get_snapshot(workspace.id, ConnectorKind.GITHUB) is None
    assert gateway.revoked == []


async def test_configuration_waits_for_old_key_sync_before_clearing_its_error(
    tmp_path: Path,
) -> None:
    _, workspace, repository, _, _, service = await setup(tmp_path)
    now = datetime.now(UTC)
    await persist_active_binding(
        repository,
        workspace_id=workspace.id,
        error_code=None,
        now=now,
    )
    lock = asyncio.Lock()
    gateway = BlockingOldKeyGateway()
    gateway.phase = ConnectionPhase.ACTIVE
    service.gateway = gateway
    service.broker_lock = lock
    sync = ConnectorSyncService(
        repository=repository,
        ledger=service.ledger,
        gateway=gateway,
        user_id="wf-installation",
        broker_lock=lock,
    )

    sync_task = asyncio.create_task(sync.sync(workspace.id, ConnectorKind.GITHUB))
    await gateway.started.wait()
    configure_task = asyncio.create_task(service.configure())
    await asyncio.sleep(0)
    assert configure_task.done() is False

    gateway.release.set()
    with pytest.raises(ComposioGatewayError) as raised:
        await sync_task
    assert raised.value.code is ComposioErrorCode.BROKER_AUTH
    await configure_task

    refreshed = await repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert refreshed is not None
    assert refreshed.last_error_code is None


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


async def test_connected_source_rejects_non_daily_auto_fetch_interval(tmp_path: Path) -> None:
    _, workspace, repository, _, _, service = await setup(tmp_path)
    await persist_active_binding(
        repository,
        workspace_id=workspace.id,
        error_code=None,
        now=datetime.now(UTC),
    )

    with pytest.raises(ValueError, match="daily"):
        await service.update_settings(
            workspace.id,
            ConnectorKind.GITHUB,
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
