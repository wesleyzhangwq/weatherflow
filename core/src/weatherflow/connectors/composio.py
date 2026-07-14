from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from weatherflow.connectors.models import ConnectionPhase, ConnectorKind
from weatherflow.extensions import CredentialBroker, CredentialRef

# Reviewed against Composio's public toolkit catalog on 2026-07-14. Upgrades are
# deliberate so an upstream schema change cannot silently alter automatic fetch.
_PINNED_READ_ACTION_VERSIONS = {
    "GITHUB_GET_THE_AUTHENTICATED_USER": "20260703_00",
    "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS": "20260703_00",
    "GMAIL_FETCH_EMAILS": "20260703_00",
    "GOOGLECALENDAR_EVENTS_LIST": "20260703_00",
}


class ComposioErrorCode(StrEnum):
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    INPUT = "input"
    NOT_FOUND = "not_found"
    TRANSPORT = "transport"
    UPSTREAM = "upstream"


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
        self.client = client or httpx.AsyncClient(timeout=30)
        self.base_url = base_url.rstrip("/")

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

    async def create_link(self, connector: ConnectorKind, *, user_id: str) -> ComposioLink:
        async def operation(key: str) -> ComposioLink:
            definition = _definition(connector)
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
                created = await self._request(
                    key,
                    "POST",
                    "/api/v3/auth_configs",
                    json={
                        "toolkit": {"slug": definition},
                        "auth_config": {
                            "type": "use_composio_managed_auth",
                            "credentials": {},
                            "restrict_to_following_tools": list(_read_actions(connector)),
                        },
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

    async def execute_read_action(
        self,
        *,
        action: str,
        connected_account_id: str,
        arguments: dict[str, Any],
    ) -> Any:
        _safe_action(action)
        version = _PINNED_READ_ACTION_VERSIONS.get(action)
        if version is None:
            raise ComposioGatewayError(ComposioErrorCode.INPUT)
        payload = await self._with_key(
            lambda key: self._request(
                key,
                "POST",
                f"/api/v3.1/tools/execute/{action}",
                json={
                    "connected_account_id": connected_account_id,
                    "version": version,
                    "arguments": arguments,
                },
            )
        )
        if payload.get("successful") is False:
            raise ComposioGatewayError(ComposioErrorCode.UPSTREAM)
        return payload.get("data", payload)

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
        except httpx.HTTPError as error:
            raise ComposioGatewayError(ComposioErrorCode.TRANSPORT, retryable=True) from error
        if not response.is_success:
            raise _status_error(response.status_code)
        try:
            payload = response.json()
        except ValueError as error:
            raise ComposioGatewayError(ComposioErrorCode.UPSTREAM) from error
        if not isinstance(payload, dict):
            raise ComposioGatewayError(ComposioErrorCode.UPSTREAM)
        return payload


def _definition(connector: ConnectorKind) -> str:
    from weatherflow.connectors.models import CONNECTOR_DEFINITIONS

    return CONNECTOR_DEFINITIONS[connector].toolkit


def _read_actions(connector: ConnectorKind) -> tuple[str, ...]:
    from weatherflow.connectors.models import CONNECTOR_DEFINITIONS

    return CONNECTOR_DEFINITIONS[connector].read_actions


def _identifier(payload: dict[str, Any]) -> str | None:
    value = payload.get("id") or payload.get("nanoid")
    return value if isinstance(value, str) and value else None


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
