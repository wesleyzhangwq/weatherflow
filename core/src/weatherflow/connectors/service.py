from datetime import UTC, datetime
from typing import Any, Protocol

from weatherflow.connectors.composio import ComposioLink, ComposioRemoteAccount
from weatherflow.connectors.models import (
    CONNECTOR_DEFINITIONS,
    ConnectHandoff,
    ConnectionAttempt,
    ConnectionPhase,
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
    ConnectorStatus,
)
from weatherflow.connectors.repository import ConnectorRepository
from weatherflow.events import Actor, Event, EventLedger, Sensitivity
from weatherflow.extensions import (
    CredentialRef,
    CredentialStore,
    CredentialUnavailableError,
)

COMPOSIO_CREDENTIAL = CredentialRef(provider="composio", name="project_api_key")


class ConnectorGateway(Protocol):
    async def validate_api_key(self, api_key: str) -> None: ...

    async def create_link(self, connector: ConnectorKind, *, user_id: str) -> ComposioLink: ...

    async def get_account(self, account_id: str) -> ComposioRemoteAccount: ...

    async def revoke(self, account_id: str) -> None: ...

    async def execute_read_action(
        self,
        *,
        action: str,
        connected_account_id: str,
        arguments: dict[str, Any],
    ) -> Any: ...


class ConnectorService:
    def __init__(
        self,
        *,
        repository: ConnectorRepository,
        ledger: EventLedger,
        credential_store: CredentialStore,
        gateway: ConnectorGateway,
        installation_id: str,
    ) -> None:
        self.repository = repository
        self.ledger = ledger
        self.credential_store = credential_store
        self.gateway = gateway
        self.installation_id = installation_id

    def configured(self) -> bool:
        try:
            return self.credential_store.resolve(COMPOSIO_CREDENTIAL) is not None
        except CredentialUnavailableError:
            return False

    async def configure(self) -> None:
        api_key = self.credential_store.resolve(COMPOSIO_CREDENTIAL)
        if api_key is None:
            raise LookupError("Composio project key is not configured")
        await self.gateway.validate_api_key(api_key)
        del api_key
        await self._event(
            "connector.configuration_changed",
            ConnectorKind.GITHUB,
            {"broker": "composio", "credential_ref": COMPOSIO_CREDENTIAL.key},
        )

    async def connect(self, workspace_id: str, connector: ConnectorKind) -> ConnectHandoff:
        if self.credential_store.resolve(COMPOSIO_CREDENTIAL) is None:
            raise LookupError("Composio project key is not configured")
        link = await self.gateway.create_link(connector, user_id=self.installation_id)
        existing = await self.repository.get_account(connector)
        if existing is None:
            account = ConnectorAccount.new(
                connector=connector,
                external_account_id=link.connected_account_id,
                credential_ref=COMPOSIO_CREDENTIAL,
            )
        else:
            account = existing.model_copy(
                update={
                    "external_account_id": link.connected_account_id,
                    "phase": ConnectionPhase.WAITING_USER,
                    "version": existing.version + 1,
                }
            )
        attempt = ConnectionAttempt.new(
            workspace_id=workspace_id,
            connector=connector,
            account_id=account.id,
            external_account_id=link.connected_account_id,
            expires_at=link.expires_at,
        )
        await self.repository.save_account(account)
        await self.repository.save_attempt(attempt)
        await self._event(
            "connector.handoff_started",
            connector,
            {
                "attempt_id": attempt.id,
                "workspace_id": workspace_id,
                "expires_at": link.expires_at.isoformat(),
            },
        )
        return ConnectHandoff(
            attempt_id=attempt.id,
            connect_url=link.redirect_url,
            expires_at=link.expires_at,
        )

    async def refresh_attempt(self, attempt_id: str) -> ConnectionAttempt:
        attempt = await self.repository.get_attempt(attempt_id)
        if attempt is None:
            raise LookupError(attempt_id)
        remote = await self.gateway.get_account(attempt.external_account_id)
        account = await self.repository.get_account_by_id(attempt.account_id)
        if account is None:
            raise LookupError(attempt.account_id)
        updated_attempt = attempt.with_phase(remote.phase)
        await self.repository.save_attempt(updated_attempt)
        if remote.phase is ConnectionPhase.ACTIVE:
            active = account.activate(display_name=remote.display_name)
            await self.repository.save_account(active)
            binding = await self.repository.get_binding(attempt.workspace_id, attempt.connector)
            if binding is None:
                binding = ConnectorBinding.new(
                    workspace_id=attempt.workspace_id,
                    connector=attempt.connector,
                    account_id=account.id,
                )
            await self.repository.save_binding(binding)
            await self._event(
                "connector.activated",
                attempt.connector,
                {
                    "attempt_id": attempt.id,
                    "workspace_id": attempt.workspace_id,
                    "account_id": account.id,
                },
            )
        elif remote.phase in {
            ConnectionPhase.ERROR,
            ConnectionPhase.EXPIRED,
            ConnectionPhase.REVOKED,
        }:
            await self.repository.save_account(account.with_phase(remote.phase))
            await self._event(
                "connector.connection_failed",
                attempt.connector,
                {"attempt_id": attempt.id, "phase": remote.phase.value},
            )
        return updated_attempt

    async def statuses(self, workspace_id: str) -> list[ConnectorStatus]:
        configured = self.configured()
        statuses: list[ConnectorStatus] = []
        for connector, definition in CONNECTOR_DEFINITIONS.items():
            account = await self.repository.get_account(connector)
            binding = await self.repository.get_binding(workspace_id, connector)
            latest_attempt = await self.repository.latest_attempt(workspace_id, connector)
            resumable_attempt = (
                latest_attempt
                if latest_attempt is not None
                and latest_attempt.phase is ConnectionPhase.WAITING_USER
                and latest_attempt.expires_at > datetime.now(UTC)
                else None
            )
            statuses.append(
                ConnectorStatus(
                    connector=connector,
                    label=definition.label,
                    phase=account.phase if account else None,
                    configured=configured,
                    connected=account is not None
                    and account.phase is ConnectionPhase.ACTIVE
                    and binding is not None,
                    display_name=account.display_name if account else None,
                    auto_fetch_enabled=binding.auto_fetch_enabled if binding else False,
                    interval_minutes=binding.interval_minutes if binding else 60,
                    last_sync_at=binding.last_sync_at if binding else None,
                    next_sync_at=binding.next_sync_at if binding else None,
                    last_error_code=binding.last_error_code if binding else None,
                    attempt_id=resumable_attempt.id if resumable_attempt else None,
                    attempt_expires_at=(
                        resumable_attempt.expires_at if resumable_attempt else None
                    ),
                )
            )
        return statuses

    async def update_settings(
        self,
        workspace_id: str,
        connector: ConnectorKind,
        *,
        auto_fetch_enabled: bool,
        interval_minutes: int,
    ) -> ConnectorBinding:
        binding = await self.repository.get_binding(workspace_id, connector)
        if binding is None:
            raise LookupError(f"connector binding unavailable: {connector.value}")
        updated = ConnectorBinding.model_validate(
            {
                **binding.model_dump(),
                "auto_fetch_enabled": auto_fetch_enabled,
                "interval_minutes": interval_minutes,
                "next_sync_at": datetime.now(UTC),
                "version": binding.version + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        await self.repository.save_binding(updated)
        await self._event(
            "connector.settings_changed",
            connector,
            {
                "workspace_id": workspace_id,
                "auto_fetch_enabled": auto_fetch_enabled,
                "interval_minutes": interval_minutes,
            },
        )
        return updated

    async def disconnect(self, connector: ConnectorKind) -> None:
        account = await self.repository.get_account(connector)
        if account is None:
            return
        await self.gateway.revoke(account.external_account_id)
        await self.repository.delete_connector(connector)
        await self._event(
            "connector.disconnected",
            connector,
            {"account_id": account.id, "derived_data_deleted": True},
        )

    async def _event(
        self, event_type: str, connector: ConnectorKind, payload: dict[str, object]
    ) -> None:
        await self.ledger.append(
            Event.new(
                type=event_type,
                actor=Actor.USER if event_type != "connector.activated" else Actor.SYSTEM,
                stream_kind="connector",
                stream_id=connector.value,
                correlation_id=connector.value,
                payload=payload,
                sensitivity=Sensitivity.SECRET_REF
                if event_type == "connector.configuration_changed"
                else Sensitivity.PRIVATE,
            )
        )
