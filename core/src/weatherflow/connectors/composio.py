from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from weatherflow.connectors.models import ConnectionPhase, ConnectorKind, OAuthSetup
from weatherflow.extensions import CredentialBroker, CredentialRef

# Reviewed against Composio's project toolkit catalog on 2026-07-15. Every
# provider action must name its frozen schema version explicitly. Upgrades are
# deliberate so an upstream schema change cannot silently alter an existing
# execution contract.
COMPOSIO_ACTION_VERSIONS = MappingProxyType(
    {
        "GITHUB_GET_THE_AUTHENTICATED_USER": "20260713_00",
        "GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER": "20260713_00",
        "GITHUB_SEARCH_COMMITS": "20260713_00",
        "GITHUB_LIST_COMMITS": "20260713_00",
        "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS": "20260713_00",
        "GITHUB_GET_A_PULL_REQUEST": "20260713_00",
        "GITHUB_LIST_BRANCHES": "20260713_00",
        "GITHUB_CREATE_AN_ISSUE": "20260713_00",
        "GITHUB_CREATE_A_PULL_REQUEST": "20260713_00",
        "GMAIL_FETCH_EMAILS": "20260702_01",
        "GMAIL_CREATE_EMAIL_DRAFT": "20260702_01",
        "GMAIL_SEND_EMAIL": "20260702_01",
        "GOOGLECALENDAR_EVENTS_LIST": "20260623_00",
        "GOOGLECALENDAR_FIND_FREE_SLOTS": "20260623_00",
        "GOOGLECALENDAR_CREATE_EVENT": "20260623_00",
        "GOOGLECALENDAR_PATCH_EVENT": "20260623_00",
        "GOOGLECALENDAR_DELETE_EVENT": "20260623_00",
    }
)

_PINNED_READ_ACTION_VERSIONS = MappingProxyType(
    {
        "GITHUB_GET_THE_AUTHENTICATED_USER": "20260713_00",
        "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS": "20260713_00",
        "GMAIL_FETCH_EMAILS": "20260702_01",
        "GOOGLECALENDAR_EVENTS_LIST": "20260623_00",
    }
)


class ComposioErrorCode(StrEnum):
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    INPUT = "input"
    NOT_FOUND = "not_found"
    TRANSPORT = "transport"
    UPSTREAM = "upstream"
    AUTH_CONFIG_REQUIRED = "auth_config_required"


class ComposioGatewayError(RuntimeError):
    def __init__(self, code: ComposioErrorCode, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(f"Composio request failed: {code.value}")


class ComposioLink(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    redirect_url: str
    connected_account_id: str = Field(min_length=1, max_length=256)
    expires_at: datetime


class ComposioRemoteAccount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    phase: ConnectionPhase
    toolkit: str
    display_name: str | None = None

    @property
    def active(self) -> bool:
        return self.phase is ConnectionPhase.ACTIVE


class ComposioGateway:
    def __init__(
        self,
        *,
        broker: CredentialBroker,
        credential_ref: CredentialRef,
        client: httpx.AsyncClient | None = None,
        base_url: str = "https://backend.composio.dev",
    ) -> None:
        self.broker = broker
        self.credential_ref = credential_ref
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=30)
        self.base_url = base_url.rstrip("/")

    async def close(self) -> None:
        if self._owns_client and not self.client.is_closed:
            await self.client.aclose()

    async def validate(self) -> None:
        await self._with_key(
            lambda key: self._request(
                key,
                "GET",
                "/api/v3/auth_configs",
                params={"limit": "1"},
            )
        )

    async def validate_api_key(self, api_key: str) -> None:
        await self._request(
            api_key,
            "GET",
            "/api/v3/auth_configs",
            params={"limit": "1"},
        )

    async def oauth_setup(self, connector: ConnectorKind) -> OAuthSetup:
        return await self._with_key(lambda key: self._toolkit_oauth_setup(key, connector))

    async def create_link(self, connector: ConnectorKind, *, user_id: str) -> ComposioLink:
        async def operation(key: str) -> ComposioLink:
            definition = _definition(connector)
            metadata_error: ComposioGatewayError | None = None
            try:
                oauth_setup = await self._toolkit_oauth_setup(key, connector)
            except ComposioGatewayError as error:
                # A pre-existing Auth Config is still safe to use when toolkit
                # metadata is temporarily unavailable. UNKNOWN may never create
                # a new managed config.
                oauth_setup = OAuthSetup.UNKNOWN
                metadata_error = error
            auth_configs = await self._request(
                key,
                "GET",
                "/api/v3/auth_configs",
                params={
                    "toolkit_slug": definition,
                    "show_disabled": "false",
                    "limit": "25",
                },
            )
            auth_config_id = _first_identifier(auth_configs)
            if auth_config_id is None:
                if metadata_error is not None:
                    raise metadata_error
                if oauth_setup is not OAuthSetup.MANAGED:
                    raise ComposioGatewayError(ComposioErrorCode.AUTH_CONFIG_REQUIRED)
                approved_actions = _approved_actions(connector)
                if not approved_actions:
                    raise ComposioGatewayError(ComposioErrorCode.AUTH_CONFIG_REQUIRED)
                auth_config = {
                    "type": "use_composio_managed_auth",
                    "credentials": {},
                    "restrict_to_following_tools": list(approved_actions),
                }
                created = await self._request(
                    key,
                    "POST",
                    "/api/v3/auth_configs",
                    json={
                        "toolkit": {"slug": definition},
                        "auth_config": auth_config,
                    },
                )
                auth_config_id = _identifier(created)
            if auth_config_id is None:
                raise ComposioGatewayError(ComposioErrorCode.UPSTREAM)
            payload = await self._request(
                key,
                "POST",
                "/api/v3/connected_accounts/link",
                json={"auth_config_id": auth_config_id, "user_id": user_id},
            )
            redirect_url = _required_string(payload, "redirect_url")
            _validate_connect_url(redirect_url)
            return ComposioLink(
                redirect_url=redirect_url,
                connected_account_id=_required_string(payload, "connected_account_id"),
                expires_at=_required_string(payload, "expires_at"),
            )

        return await self._with_key(operation)

    async def _toolkit_oauth_setup(self, key: str, connector: ConnectorKind) -> OAuthSetup:
        toolkit = _definition(connector)
        payload = await self._request(
            key,
            "GET",
            f"/api/v3.1/toolkits/{_safe_identifier(toolkit)}",
        )
        schemes = payload.get("composio_managed_auth_schemes")
        if not isinstance(schemes, list):
            return OAuthSetup.UNKNOWN
        return OAuthSetup.MANAGED if schemes else OAuthSetup.BRING_YOUR_OWN

    async def get_account(self, account_id: str) -> ComposioRemoteAccount:
        payload = await self._with_key(
            lambda key: self._request(
                key, "GET", f"/api/v3/connected_accounts/{_safe_identifier(account_id)}"
            )
        )
        toolkit_value = payload.get("toolkit")
        toolkit = toolkit_value.get("slug") if isinstance(toolkit_value, dict) else toolkit_value
        if not isinstance(toolkit, str) or not toolkit:
            toolkit = "unknown"
        display_name = _optional_display_name(payload)
        return ComposioRemoteAccount(
            id=_required_string(payload, "id"),
            phase=_normalize_phase(str(payload.get("status", ""))),
            toolkit=toolkit,
            display_name=display_name,
        )

    async def ensure_action_allowlist(
        self,
        connector: ConnectorKind,
        *,
        connected_account_id: str,
        user_id: str,
    ) -> None:
        safe_account_id = _safe_identifier(connected_account_id)
        safe_user_id = _safe_identifier(user_id)
        expected_toolkit = _definition(connector)
        approved_actions = _approved_actions(connector)
        if not approved_actions:
            raise ComposioGatewayError(ComposioErrorCode.AUTH_CONFIG_REQUIRED)

        async def operation(key: str) -> None:
            account = await self._request(
                key,
                "GET",
                f"/api/v3/connected_accounts/{safe_account_id}",
            )
            toolkit_value = account.get("toolkit")
            toolkit = (
                toolkit_value.get("slug") if isinstance(toolkit_value, dict) else toolkit_value
            )
            if (
                account.get("id") != safe_account_id
                or account.get("user_id") != safe_user_id
                or toolkit != expected_toolkit
                or _normalize_phase(str(account.get("status", ""))) is not ConnectionPhase.ACTIVE
            ):
                raise ComposioGatewayError(ComposioErrorCode.AUTH)
            account_auth_config = account.get("auth_config")
            if not isinstance(account_auth_config, dict):
                raise ComposioGatewayError(ComposioErrorCode.UPSTREAM)
            auth_config_id = _identifier(account_auth_config)
            if auth_config_id is None:
                raise ComposioGatewayError(ComposioErrorCode.UPSTREAM)
            safe_auth_config_id = _safe_identifier(auth_config_id)
            auth_config = await self._request(
                key,
                "GET",
                f"/api/v3/auth_configs/{safe_auth_config_id}",
            )
            current_actions = _string_set(auth_config.get("restrict_to_following_tools"))
            required_actions = frozenset(approved_actions)
            if required_actions.issubset(current_actions):
                return
            if (
                auth_config.get("is_composio_managed") is not True
                or auth_config.get("type") != "default"
            ):
                raise ComposioGatewayError(ComposioErrorCode.AUTH_CONFIG_REQUIRED)
            await self._request(
                key,
                "PATCH",
                f"/api/v3/auth_configs/{safe_auth_config_id}",
                json={
                    "type": "default",
                    "restrict_to_following_tools": list(approved_actions),
                },
            )
            verified = await self._request(
                key,
                "GET",
                f"/api/v3/auth_configs/{safe_auth_config_id}",
            )
            verified_actions = _string_set(verified.get("restrict_to_following_tools"))
            if not required_actions.issubset(verified_actions):
                raise ComposioGatewayError(ComposioErrorCode.UPSTREAM)

        await self._with_key(operation)

    async def execute_read_action(
        self,
        *,
        action: str,
        connected_account_id: str,
        user_id: str,
        arguments: dict[str, Any],
    ) -> Any:
        _safe_action(action)
        version = _PINNED_READ_ACTION_VERSIONS.get(action)
        if version is None:
            raise ComposioGatewayError(ComposioErrorCode.INPUT)
        return await self.execute_tool(
            action=action,
            version=version,
            connected_account_id=connected_account_id,
            user_id=user_id,
            arguments=arguments,
        )

    async def execute_tool(
        self,
        *,
        action: str,
        version: str,
        connected_account_id: str,
        user_id: str,
        arguments: dict[str, Any],
    ) -> Any:
        _safe_action(action)
        expected_version = COMPOSIO_ACTION_VERSIONS.get(action)
        if expected_version is None or version != expected_version:
            raise ComposioGatewayError(ComposioErrorCode.INPUT)
        safe_account_id = _safe_identifier(connected_account_id)
        safe_user_id = _safe_identifier(user_id)
        payload = await self._with_key(
            lambda key: self._request(
                key,
                "POST",
                f"/api/v3.1/tools/execute/{action}",
                json={
                    "connected_account_id": safe_account_id,
                    "user_id": safe_user_id,
                    "version": version,
                    "arguments": arguments,
                },
            )
        )
        if payload.get("successful") is not True:
            raise ComposioGatewayError(ComposioErrorCode.UPSTREAM)
        return payload.get("data", {})

    async def revoke(self, account_id: str) -> None:
        await self._with_key(
            lambda key: self._request(
                key,
                "POST",
                f"/api/v3.1/connected_accounts/{_safe_identifier(account_id)}/revoke",
            )
        )

    async def _with_key(self, operation: Callable[[str], Awaitable[Any]]) -> Any:
        return await self.broker.call(self.credential_ref, operation)

    async def _request(
        self,
        key: str,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self.client.request(
                method,
                f"{self.base_url}{path}",
                headers={"x-api-key": key},
                params=params,
                json=json,
            )
        except httpx.HTTPError:
            raise ComposioGatewayError(ComposioErrorCode.TRANSPORT, retryable=True) from None
        if not response.is_success:
            raise _status_error(response.status_code)
        try:
            payload = response.json()
        except ValueError:
            raise ComposioGatewayError(ComposioErrorCode.UPSTREAM) from None
        if not isinstance(payload, dict):
            raise ComposioGatewayError(ComposioErrorCode.UPSTREAM)
        return payload


def _definition(connector: ConnectorKind) -> str:
    from weatherflow.connectors.models import CONNECTOR_DEFINITIONS

    return CONNECTOR_DEFINITIONS[connector].toolkit


def _approved_actions(connector: ConnectorKind) -> tuple[str, ...]:
    from weatherflow.connectors.models import CONNECTOR_DEFINITIONS

    return CONNECTOR_DEFINITIONS[connector].reviewed_auth_actions


def _identifier(payload: dict[str, Any]) -> str | None:
    value = payload.get("id") or payload.get("nanoid")
    return value if isinstance(value, str) and value else None


def _string_set(value: Any) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(item for item in value if isinstance(item, str) and item)


def _first_identifier(payload: dict[str, Any]) -> str | None:
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        value = _identifier(item)
        if value is not None:
            return value
    return None


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ComposioGatewayError(ComposioErrorCode.UPSTREAM)
    return value


def _optional_display_name(payload: dict[str, Any]) -> str | None:
    for key in ("display_name", "alias", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:300]
    return None


def _normalize_phase(value: str) -> ConnectionPhase:
    normalized = value.upper()
    if normalized in {"ACTIVE", "CONNECTED"}:
        return ConnectionPhase.ACTIVE
    if normalized in {"INITIATED", "INITIALIZING", "PENDING"}:
        return ConnectionPhase.WAITING_USER
    if normalized == "EXPIRED":
        return ConnectionPhase.EXPIRED
    if normalized in {"REVOKED", "DISABLED"}:
        return ConnectionPhase.REVOKED
    return ConnectionPhase.ERROR


def _validate_connect_url(value: str) -> None:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        hostname == "composio.dev" or hostname.endswith(".composio.dev")
    ):
        raise ComposioGatewayError(ComposioErrorCode.UPSTREAM)


def _safe_identifier(value: str) -> str:
    if not value or not all(character.isalnum() or character in "_-" for character in value):
        raise ComposioGatewayError(ComposioErrorCode.INPUT)
    return value


def _safe_action(value: str) -> None:
    allowed = all(
        character.isupper() or character.isdigit() or character == "_" for character in value
    )
    if not value or not allowed:
        raise ComposioGatewayError(ComposioErrorCode.INPUT)


def _status_error(status: int) -> ComposioGatewayError:
    if status in {401, 403}:
        return ComposioGatewayError(ComposioErrorCode.AUTH)
    if status == 404:
        return ComposioGatewayError(ComposioErrorCode.NOT_FOUND)
    if status == 429:
        return ComposioGatewayError(ComposioErrorCode.RATE_LIMIT, retryable=True)
    if status in {400, 409, 422}:
        return ComposioGatewayError(ComposioErrorCode.INPUT)
    return ComposioGatewayError(ComposioErrorCode.UPSTREAM, retryable=status >= 500)
