import asyncio
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Protocol

from weatherflow.connectors.composio import (
    ComposioGatewayError,
    ComposioLink,
    ComposioRemoteAccount,
)
from weatherflow.connectors.models import (
    CONNECTOR_DEFINITIONS,
    ConnectHandoff,
    ConnectionAttempt,
    ConnectionPhase,
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
    ConnectorStatus,
    ConversationAccess,
    OAuthSetup,
)
from weatherflow.connectors.repository import ConnectorRepository
from weatherflow.events import Actor, Event, EventLedger, Sensitivity
from weatherflow.extensions import (
    CredentialRef,
    CredentialStore,
    CredentialUnavailableError,
)

COMPOSIO_CREDENTIAL = CredentialRef(provider="composio", name="project_api_key")
OAUTH_SETUP_CACHE_SECONDS = 10 * 60
OAUTH_SETUP_ERROR_CACHE_SECONDS = 60


class ConnectorGateway(Protocol):
    async def validate_api_key(self, api_key: str) -> None: ...

    async def oauth_setup(self, connector: ConnectorKind) -> OAuthSetup: ...

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

    async def execute_tool(
        self,
        *,
        action: str,
        version: str,
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
        self._oauth_setup_cache: dict[ConnectorKind, tuple[float, OAuthSetup]] = {}

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
        self._oauth_setup_cache.clear()
        await self._event(
            "connector.configuration_changed",
            ConnectorKind.GITHUB,
            {"broker": "composio", "credential_ref": COMPOSIO_CREDENTIAL.key},
        )

    async def connect(self, workspace_id: str, connector: ConnectorKind) -> ConnectHandoff:
        if self.credential_store.resolve(COMPOSIO_CREDENTIAL) is None:
            raise LookupError("Composio project key is not configured")
        link = await self.gateway.create_link(connector, user_id=self.installation_id)
        account = ConnectorAccount.new(
            workspace_id=workspace_id,
            connector=connector,
            external_account_id=link.connected_account_id,
            credential_ref=COMPOSIO_CREDENTIAL,
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
        if attempt.phase is not ConnectionPhase.WAITING_USER:
            return attempt
        if attempt.expires_at <= datetime.now(UTC):
            expired, _, changed = await self.repository.finalize_attempt(
                attempt.id,
                phase=ConnectionPhase.EXPIRED,
            )
            if changed:
                await self._event(
                    "connector.connection_failed",
                    attempt.connector,
                    {"attempt_id": attempt.id, "phase": expired.phase.value},
                )
            return expired
        remote = await self.gateway.get_account(attempt.external_account_id)
        expected_toolkit = CONNECTOR_DEFINITIONS[attempt.connector].toolkit
        if remote.toolkit != expected_toolkit:
            remote = remote.model_copy(update={"phase": ConnectionPhase.ERROR})
        if remote.phase is ConnectionPhase.WAITING_USER:
            return attempt
        updated_attempt, binding, changed = await self.repository.finalize_attempt(
            attempt.id,
            phase=remote.phase,
            display_name=remote.display_name,
        )
        if remote.phase is ConnectionPhase.ACTIVE:
            if not changed or binding is None:
                return updated_attempt
            await self._event(
                "connector.activated",
                attempt.connector,
                {
                    "attempt_id": attempt.id,
                    "workspace_id": attempt.workspace_id,
                    "account_id": binding.account_id,
                },
            )
        elif (
            remote.phase
            in {
                ConnectionPhase.ERROR,
                ConnectionPhase.EXPIRED,
                ConnectionPhase.REVOKED,
            }
            and changed
        ):
            await self._event(
                "connector.connection_failed",
                attempt.connector,
                {"attempt_id": attempt.id, "phase": remote.phase.value},
            )
        return updated_attempt

    async def statuses(self, workspace_id: str) -> list[ConnectorStatus]:
        configured = self.configured()
        oauth_setups = (
            await asyncio.gather(
                *(self._oauth_setup(connector) for connector in CONNECTOR_DEFINITIONS)
            )
            if configured
            else [OAuthSetup.UNKNOWN] * len(CONNECTOR_DEFINITIONS)
        )
        statuses: list[ConnectorStatus] = []
        for (connector, definition), oauth_setup in zip(
            CONNECTOR_DEFINITIONS.items(), oauth_setups, strict=True
        ):
            binding = await self.repository.get_binding(workspace_id, connector)
            account = (
                await self.repository.get_account_by_id(workspace_id, binding.account_id)
                if binding is not None
                else None
            )
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
                    category=definition.category,
                    toolkit=definition.toolkit,
                    auto_fetch_supported=definition.auto_fetch_supported,
                    conversation_tools_supported=definition.conversation_tools_supported,
                    oauth_setup=oauth_setup,
                    phase=(
                        account.phase
                        if account
                        else latest_attempt.phase
                        if latest_attempt
                        else None
                    ),
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
                    conversation_access=(
                        binding.conversation_access if binding else ConversationAccess.DISABLED
                    ),
                    allowed_tool_ids=(
                        tuple(sorted(binding.conversation_tool_ids)) if binding else ()
                    ),
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
        if auto_fetch_enabled and not CONNECTOR_DEFINITIONS[connector].auto_fetch_supported:
            raise PermissionError(f"automatic fetch unsupported: {connector.value}")
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

    async def update_conversation_access(
        self,
        workspace_id: str,
        connector: ConnectorKind,
        access: ConversationAccess,
    ) -> ConnectorBinding:
        from weatherflow.capabilities import ToolEffect
        from weatherflow.connectors.tools import COMPOSIO_TOOL_DEFINITIONS

        binding = await self.repository.get_binding(workspace_id, connector)
        if binding is None or not binding.enabled:
            raise LookupError(f"connector binding unavailable: {connector.value}")
        definitions = tuple(
            definition
            for definition in COMPOSIO_TOOL_DEFINITIONS
            if definition.connector is connector
        )
        if (
            access is not ConversationAccess.DISABLED
            and not CONNECTOR_DEFINITIONS[connector].conversation_tools_supported
        ):
            raise PermissionError(f"conversation tools unsupported: {connector.value}")
        if access is ConversationAccess.DISABLED:
            selected = frozenset()
        elif access is ConversationAccess.READ:
            selected = frozenset(
                definition.tool_id
                for definition in definitions
                if definition.effect is ToolEffect.NETWORK_READ
            )
        else:
            selected = frozenset(definition.tool_id for definition in definitions)
        required_scopes = {
            definition.required_scope
            for definition in definitions
            if definition.tool_id in selected
        }
        if not required_scopes.issubset(binding.granted_scopes):
            raise PermissionError("connector must be reauthorized for requested tools")
        updated = binding.with_conversation_access(access, tool_ids=selected)
        await self.repository.save_binding(updated)
        await self._event(
            "connector.conversation_access_changed",
            connector,
            {
                "workspace_id": workspace_id,
                "access": access.value,
                "tool_ids": sorted(selected),
                "grant_revision": updated.conversation_grant_revision,
            },
        )
        return updated

    async def _oauth_setup(self, connector: ConnectorKind) -> OAuthSetup:
        now = monotonic()
        cached = self._oauth_setup_cache.get(connector)
        if cached is not None and cached[0] > now:
            return cached[1]
        if not CONNECTOR_DEFINITIONS[connector].reviewed_auth_actions:
            setup = OAuthSetup.UNKNOWN
            self._oauth_setup_cache[connector] = (
                now + OAUTH_SETUP_CACHE_SECONDS,
                setup,
            )
            return setup
        try:
            setup = await self.gateway.oauth_setup(connector)
        except ComposioGatewayError:
            setup = OAuthSetup.UNKNOWN
            ttl = OAUTH_SETUP_ERROR_CACHE_SECONDS
        else:
            ttl = OAUTH_SETUP_CACHE_SECONDS
        self._oauth_setup_cache[connector] = (now + ttl, setup)
        return setup

    async def disconnect(self, workspace_id: str, connector: ConnectorKind) -> None:
        binding = await self.repository.get_binding(workspace_id, connector)
        if binding is None:
            return
        account = await self.repository.get_account_by_id(workspace_id, binding.account_id)
        await self.repository.delete_snapshot(workspace_id, connector)
        await self.repository.delete_binding(workspace_id, connector)
        remote_revoked = False
        if (
            account is not None
            and await self.repository.count_bindings_for_account(account.id) == 0
        ):
            await self.gateway.revoke(account.external_account_id)
            await self.repository.delete_account(workspace_id, account.id)
            remote_revoked = True
        await self._event(
            "connector.disconnected",
            connector,
            {
                "workspace_id": workspace_id,
                "account_id": binding.account_id,
                "derived_data_deleted": True,
                "remote_revoked": remote_revoked,
            },
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
