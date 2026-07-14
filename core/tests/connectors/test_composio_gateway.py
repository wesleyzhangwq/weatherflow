import json
from datetime import datetime

import httpx
import pytest

from weatherflow.connectors import ConnectorKind
from weatherflow.connectors.composio import (
    COMPOSIO_ACTION_VERSIONS,
    ComposioErrorCode,
    ComposioGateway,
    ComposioGatewayError,
)
from weatherflow.connectors.models import OAuthSetup
from weatherflow.extensions import CredentialBroker, CredentialRef, MappingCredentialStore

SECRET = "composio-project-secret"
REFERENCE = CredentialRef(provider="composio", name="project_api_key")


def gateway_transport(requests: list[httpx.Request]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["x-api-key"] == SECRET
        if request.url.path == "/api/v3.1/toolkits/github":
            return httpx.Response(200, json={"composio_managed_auth_schemes": []})
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
            assert '"version":"20260703_00"' in body
            assert '"version":"latest"' not in body
            return httpx.Response(200, json={"successful": True, "data": {"login": "wesz"}})
        if request.url.path == "/api/v3.1/tools/execute/GITHUB_CREATE_AN_ISSUE":
            assert request.method == "POST"
            assert request.content == (
                b'{"connected_account_id":"ca_github","version":"20260703_00",'
                b'"arguments":{"owner":"tinyhumansai","repo":"openhuman",'
                b'"title":"Review WeatherFlow"}}'
            )
            return httpx.Response(200, json={"successful": True, "data": {"number": 42}})
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
    created = await gateway.execute_tool(
        action="GITHUB_CREATE_AN_ISSUE",
        version=COMPOSIO_ACTION_VERSIONS["GITHUB_CREATE_AN_ISSUE"],
        connected_account_id=link.connected_account_id,
        arguments={
            "owner": "tinyhumansai",
            "repo": "openhuman",
            "title": "Review WeatherFlow",
        },
    )
    await gateway.revoke(link.connected_account_id)

    assert link.redirect_url == "https://connect.composio.dev/link-token"
    assert link.connected_account_id == "ca_github"
    assert isinstance(link.expires_at, datetime)
    assert remote.active is True
    assert data == {"login": "wesz"}
    assert created == {"number": 42}
    paths = [request.url.path for request in requests]
    assert all("initiate" not in path and "/v2" not in path for path in paths)


async def test_gateway_closes_only_the_http_client_it_owns() -> None:
    gateway = ComposioGateway(
        broker=CredentialBroker(MappingCredentialStore({REFERENCE.key: SECRET})),
        credential_ref=REFERENCE,
    )
    owned = gateway.client

    await gateway.close()

    assert owned.is_closed

    external = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: None))
    injected = ComposioGateway(
        broker=CredentialBroker(MappingCredentialStore({REFERENCE.key: SECRET})),
        credential_ref=REFERENCE,
        client=external,
    )
    await injected.close()
    assert external.is_closed is False
    await external.aclose()


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
        if request.url.path == "/api/v3.1/toolkits/gmail":
            return httpx.Response(
                200,
                json={"composio_managed_auth_schemes": ["OAUTH2"]},
            )
        if request.url.path == "/api/v3/auth_configs" and request.method == "GET":
            return httpx.Response(200, json={"items": []})
        if request.url.path == "/api/v3/auth_configs" and request.method == "POST":
            payload = json.loads(request.content)
            assert payload == {
                "toolkit": {"slug": "gmail"},
                "auth_config": {
                    "type": "use_composio_managed_auth",
                    "credentials": {},
                    "restrict_to_following_tools": [
                        "GMAIL_FETCH_EMAILS",
                        "GMAIL_CREATE_EMAIL_DRAFT",
                        "GMAIL_SEND_EMAIL",
                    ],
                },
            }
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
    assert [request.method for request in requests] == ["GET", "GET", "POST", "POST"]
    assert requests[0].url.path == "/api/v3.1/toolkits/gmail"


async def test_missing_auth_config_without_managed_auth_fails_closed() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v3.1/toolkits/googlecalendar":
            return httpx.Response(200, json={"composio_managed_auth_schemes": []})
        if request.url.path == "/api/v3/auth_configs":
            return httpx.Response(200, json={"items": []})
        raise AssertionError(request.url)

    gateway = ComposioGateway(
        broker=CredentialBroker(MappingCredentialStore({REFERENCE.key: SECRET})),
        credential_ref=REFERENCE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ComposioGatewayError) as raised:
        await gateway.create_link(ConnectorKind.GOOGLE_CALENDAR, user_id="wf-installation")

    assert raised.value.code is ComposioErrorCode.AUTH_CONFIG_REQUIRED
    assert [request.url.path for request in requests] == [
        "/api/v3.1/toolkits/googlecalendar",
        "/api/v3/auth_configs",
    ]


async def test_existing_byo_auth_config_can_link_without_managed_auth() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v3.1/toolkits/googlecalendar":
            return httpx.Response(200, json={"composio_managed_auth_schemes": []})
        if request.url.path == "/api/v3/auth_configs":
            return httpx.Response(200, json={"items": [{"id": "ac_calendar_byo"}]})
        if request.url.path == "/api/v3/connected_accounts/link":
            return httpx.Response(
                201,
                json={
                    "redirect_url": "https://connect.composio.dev/calendar-link",
                    "connected_account_id": "ca_calendar",
                    "expires_at": "2026-07-13T12:05:00Z",
                },
            )
        raise AssertionError(request.url)

    gateway = ComposioGateway(
        broker=CredentialBroker(MappingCredentialStore({REFERENCE.key: SECRET})),
        credential_ref=REFERENCE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    link = await gateway.create_link(ConnectorKind.GOOGLE_CALENDAR, user_id="wf-installation")

    assert link.connected_account_id == "ca_calendar"
    assert all(request.method != "POST" for request in requests[:2])


async def test_existing_auth_config_can_link_when_toolkit_metadata_is_unavailable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3.1/toolkits/slack":
            return httpx.Response(503)
        if request.url.path == "/api/v3/auth_configs":
            return httpx.Response(200, json={"items": [{"id": "ac_slack_existing"}]})
        if request.url.path == "/api/v3/connected_accounts/link":
            return httpx.Response(
                201,
                json={
                    "redirect_url": "https://connect.composio.dev/slack-existing",
                    "connected_account_id": "ca_slack",
                    "expires_at": "2026-07-13T12:05:00Z",
                },
            )
        raise AssertionError(request.url)

    gateway = ComposioGateway(
        broker=CredentialBroker(MappingCredentialStore({REFERENCE.key: SECRET})),
        credential_ref=REFERENCE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    link = await gateway.create_link(ConnectorKind.SLACK, user_id="wf-installation")

    assert link.connected_account_id == "ca_slack"


async def test_toolkit_oauth_setup_is_derived_from_authoritative_project_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3.1/toolkits/slack"
        return httpx.Response(
            200,
            json={"composio_managed_auth_schemes": [{"auth_scheme": "OAUTH2"}]},
        )

    gateway = ComposioGateway(
        broker=CredentialBroker(MappingCredentialStore({REFERENCE.key: SECRET})),
        credential_ref=REFERENCE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    assert await gateway.oauth_setup(ConnectorKind.SLACK) is OAuthSetup.MANAGED


async def test_catalog_managed_auth_is_always_restricted_to_reviewed_actions() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v3.1/toolkits/slack":
            return httpx.Response(200, json={"composio_managed_auth_schemes": ["OAUTH2"]})
        if request.url.path == "/api/v3/auth_configs" and request.method == "GET":
            return httpx.Response(200, json={"items": []})
        if request.url.path == "/api/v3/auth_configs" and request.method == "POST":
            assert json.loads(request.content)["auth_config"] == {
                "type": "use_composio_managed_auth",
                "credentials": {},
                "restrict_to_following_tools": ["SLACK_SEARCH_MESSAGES"],
            }
            return httpx.Response(201, json={"id": "ac_slack_managed"})
        if request.url.path == "/api/v3/connected_accounts/link":
            return httpx.Response(
                201,
                json={
                    "redirect_url": "https://connect.composio.dev/slack-link",
                    "connected_account_id": "ca_slack",
                    "expires_at": "2026-07-13T12:05:00Z",
                },
            )
        raise AssertionError(request.url)

    gateway = ComposioGateway(
        broker=CredentialBroker(MappingCredentialStore({REFERENCE.key: SECRET})),
        credential_ref=REFERENCE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    link = await gateway.create_link(ConnectorKind.SLACK, user_id="wf-installation")

    assert link.connected_account_id == "ca_slack"


async def test_catalog_entry_without_reviewed_action_never_creates_managed_auth() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v3.1/toolkits/trello":
            return httpx.Response(200, json={"composio_managed_auth_schemes": ["OAUTH1"]})
        if request.url.path == "/api/v3/auth_configs":
            return httpx.Response(200, json={"items": []})
        raise AssertionError(request.url)

    gateway = ComposioGateway(
        broker=CredentialBroker(MappingCredentialStore({REFERENCE.key: SECRET})),
        credential_ref=REFERENCE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ComposioGatewayError) as raised:
        await gateway.create_link(ConnectorKind.TRELLO, user_id="wf-installation")

    assert raised.value.code is ComposioErrorCode.AUTH_CONFIG_REQUIRED
    assert all(request.method != "POST" for request in requests)


@pytest.mark.parametrize(
    ("action", "version"),
    [
        ("COMPOSIO_EXECUTE", "20260703_00"),
        ("GITHUB_CREATE_AN_ISSUE", "latest"),
        ("GITHUB_CREATE_AN_ISSUE", "20260704_00"),
    ],
)
async def test_execute_tool_rejects_unknown_action_or_version_before_network(
    action: str,
    version: str,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"successful": True, "data": {}})

    gateway = ComposioGateway(
        broker=CredentialBroker(MappingCredentialStore({REFERENCE.key: SECRET})),
        credential_ref=REFERENCE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ComposioGatewayError) as raised:
        await gateway.execute_tool(
            action=action,
            version=version,
            connected_account_id="ca_github",
            arguments={},
        )

    assert raised.value.code is ComposioErrorCode.INPUT
    assert requests == []


async def test_execute_tool_redacts_provider_failure_payload() -> None:
    provider_secret = "provider-secret-that-must-never-escape"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "successful": False,
                "error": {"message": provider_secret * 10_000},
            },
        )

    gateway = ComposioGateway(
        broker=CredentialBroker(MappingCredentialStore({REFERENCE.key: SECRET})),
        credential_ref=REFERENCE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ComposioGatewayError) as raised:
        await gateway.execute_tool(
            action="GMAIL_SEND_EMAIL",
            version=COMPOSIO_ACTION_VERSIONS["GMAIL_SEND_EMAIL"],
            connected_account_id="ca_gmail",
            arguments={"recipient_email": "user@example.com", "subject": "Hi", "body": "Hi"},
        )

    assert raised.value.code is ComposioErrorCode.UPSTREAM
    assert provider_secret not in str(raised.value)
    assert provider_secret not in repr(raised.value)
