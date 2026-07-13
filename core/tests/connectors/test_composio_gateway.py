from datetime import datetime

import httpx
import pytest

from weatherflow.connectors import ConnectorKind
from weatherflow.connectors.composio import (
    ComposioErrorCode,
    ComposioGateway,
    ComposioGatewayError,
)
from weatherflow.extensions import CredentialBroker, CredentialRef, MappingCredentialStore

SECRET = "composio-project-secret"
REFERENCE = CredentialRef(provider="composio", name="project_api_key")


def gateway_transport(requests: list[httpx.Request]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["x-api-key"] == SECRET
        if request.url.path == "/api/v3/auth_configs":
            return httpx.Response(200, json={"items": [{"id": "ac_github"}]})
        if request.url.path == "/api/v3/connected_accounts/link":
            assert request.method == "POST"
            assert request.content == (
                b'{"auth_config_id":"ac_github","user_id":"wf-installation"}'
            )
            return httpx.Response(
                201,
                json={
                    "redirect_url": "https://connect.composio.dev/link-token",
                    "connected_account_id": "ca_github",
                    "expires_at": "2026-07-13T12:05:00Z",
                    "link_token": "must-not-escape",
                },
            )
        if request.url.path == "/api/v3/connected_accounts/ca_github":
            return httpx.Response(
                200,
                json={
                    "id": "ca_github",
                    "status": "ACTIVE",
                    "toolkit": {"slug": "github"},
                    "user_id": "wf-installation",
                },
            )
        if request.url.path == "/api/v3.1/tools/execute/GITHUB_GET_THE_AUTHENTICATED_USER":
            body = request.content.decode()
            assert '"connected_account_id":"ca_github"' in body
            assert '"version":"latest"' in body
            return httpx.Response(200, json={"successful": True, "data": {"login": "wesz"}})
        if request.url.path == "/api/v3.1/connected_accounts/ca_github/revoke":
            return httpx.Response(200, json={"revoked": True})
        raise AssertionError(request.url)

    return httpx.MockTransport(handler)


async def test_gateway_uses_connect_link_v3_and_versioned_v31_execution() -> None:
    requests: list[httpx.Request] = []
    gateway = ComposioGateway(
        broker=CredentialBroker(MappingCredentialStore({REFERENCE.key: SECRET})),
        credential_ref=REFERENCE,
        client=httpx.AsyncClient(transport=gateway_transport(requests)),
    )

    link = await gateway.create_link(ConnectorKind.GITHUB, user_id="wf-installation")
    remote = await gateway.get_account(link.connected_account_id)
    data = await gateway.execute_read_action(
        action="GITHUB_GET_THE_AUTHENTICATED_USER",
        connected_account_id=link.connected_account_id,
        arguments={},
    )
    await gateway.revoke(link.connected_account_id)

    assert link.redirect_url == "https://connect.composio.dev/link-token"
    assert link.connected_account_id == "ca_github"
    assert isinstance(link.expires_at, datetime)
    assert remote.active is True
    assert data == {"login": "wesz"}
    paths = [request.url.path for request in requests]
    assert all("initiate" not in path and "/v2" not in path for path in paths)


async def test_gateway_classifies_and_redacts_upstream_auth_errors() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": SECRET}})

    gateway = ComposioGateway(
        broker=CredentialBroker(MappingCredentialStore({REFERENCE.key: SECRET})),
        credential_ref=REFERENCE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ComposioGatewayError) as raised:
        await gateway.validate()

    assert raised.value.code is ComposioErrorCode.AUTH
    assert SECRET not in str(raised.value)


async def test_missing_auth_config_is_created_with_managed_auth_and_fixed_actions() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v3/auth_configs" and request.method == "GET":
            return httpx.Response(200, json={"items": []})
        if request.url.path == "/api/v3/auth_configs" and request.method == "POST":
            assert request.content == (
                b'{"toolkit":{"slug":"gmail"},"auth_config":'
                b'{"type":"use_composio_managed_auth","credentials":{},'
                b'"restrict_to_following_tools":["GMAIL_FETCH_EMAILS"]}}'
            )
            return httpx.Response(201, json={"id": "ac_gmail_managed"})
        if request.url.path == "/api/v3/connected_accounts/link":
            assert b'"auth_config_id":"ac_gmail_managed"' in request.content
            return httpx.Response(
                201,
                json={
                    "redirect_url": "https://connect.composio.dev/gmail-link",
                    "connected_account_id": "ca_gmail",
                    "expires_at": "2026-07-13T12:05:00Z",
                },
            )
        raise AssertionError(request.url)

    gateway = ComposioGateway(
        broker=CredentialBroker(MappingCredentialStore({REFERENCE.key: SECRET})),
        credential_ref=REFERENCE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    link = await gateway.create_link(ConnectorKind.GMAIL, user_id="wf-installation")

    assert link.connected_account_id == "ca_gmail"
    assert [request.method for request in requests] == ["GET", "POST", "POST"]
