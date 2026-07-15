from datetime import UTC, datetime, timedelta
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.connectors import (
    ComposioErrorCode,
    ComposioGatewayError,
    ConnectHandoff,
    ConnectionAttempt,
    ConnectionPhase,
    ConnectorKind,
    ConnectorService,
    ConnectorSnapshot,
    ConnectorStatus,
    ConnectorSyncService,
)


async def test_connector_api_exposes_handoff_status_settings_sync_and_disconnect(
    tmp_path: Path, monkeypatch
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    workspace_id = container.default_workspace.id
    now = datetime.now(UTC)
    calls: list[tuple[str, object]] = []
    attempt = ConnectionAttempt.new(
        workspace_id=workspace_id,
        connector=ConnectorKind.GITHUB,
        account_id="account-1",
        external_account_id="ca_github",
        expires_at=now + timedelta(minutes=5),
        now=now,
    )

    async def configure(_service: ConnectorService) -> None:
        calls.append(("configure", None))

    async def statuses(_service: ConnectorService, requested_workspace_id: str):
        calls.append(("statuses", requested_workspace_id))
        return [
            ConnectorStatus(
                connector=ConnectorKind.GITHUB,
                label="GitHub",
                category="development",
                toolkit="github",
                auto_fetch_supported=True,
                conversation_tools_supported=True,
                oauth_setup="managed",
                phase=ConnectionPhase.ACTIVE,
                configured=True,
                connected=True,
            )
        ]

    async def connect(
        _service: ConnectorService,
        requested_workspace_id: str,
        connector: ConnectorKind,
    ) -> ConnectHandoff:
        calls.append(("connect", (requested_workspace_id, connector)))
        return ConnectHandoff(
            attempt_id=attempt.id,
            connect_url="https://connect.composio.dev/opaque",
            expires_at=attempt.expires_at,
        )

    async def refresh(_service: ConnectorService, attempt_id: str) -> ConnectionAttempt:
        calls.append(("refresh", attempt_id))
        return attempt.with_phase(ConnectionPhase.ACTIVE)

    async def update_settings(
        _service: ConnectorService,
        requested_workspace_id: str,
        connector: ConnectorKind,
        *,
        auto_fetch_enabled: bool,
        interval_minutes: int,
    ):
        calls.append(
            (
                "settings",
                (requested_workspace_id, connector, auto_fetch_enabled, interval_minutes),
            )
        )
        return None

    async def sync(
        _service: ConnectorSyncService,
        requested_workspace_id: str,
        connector: ConnectorKind,
    ) -> ConnectorSnapshot:
        calls.append(("sync", (requested_workspace_id, connector)))
        return ConnectorSnapshot(
            workspace_id=requested_workspace_id,
            connector=connector,
            fetched_at=now,
            expires_at=now + timedelta(hours=1),
            items=(),
        )

    async def disconnect(
        _service: ConnectorService,
        requested_workspace_id: str,
        connector: ConnectorKind,
    ) -> None:
        calls.append(("disconnect", (requested_workspace_id, connector)))

    monkeypatch.setattr(ConnectorService, "configure", configure)
    monkeypatch.setattr(ConnectorService, "statuses", statuses)
    monkeypatch.setattr(ConnectorService, "connect", connect)
    monkeypatch.setattr(ConnectorService, "refresh_attempt", refresh)
    monkeypatch.setattr(ConnectorService, "update_settings", update_settings)
    monkeypatch.setattr(ConnectorSyncService, "sync", sync)
    monkeypatch.setattr(ConnectorService, "disconnect", disconnect)
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        configured = await client.post("/v1/connectors/configure")
        openapi = await client.get("/openapi.json")
        listed = await client.get("/v1/connectors", params={"workspace_id": workspace_id})
        handoff = await client.post(
            "/v1/connectors/github/connect", params={"workspace_id": workspace_id}
        )
        refreshed = await client.get(f"/v1/connector-attempts/{attempt.id}")
        settings = await client.post(
            "/v1/connectors/github/settings",
            params={"workspace_id": workspace_id},
            json={"auto_fetch_enabled": False, "interval_minutes": 120},
        )
        synced = await client.post(
            "/v1/connectors/github/sync", params={"workspace_id": workspace_id}
        )
        disconnected = await client.post(
            "/v1/connectors/github/disconnect",
            params={"workspace_id": workspace_id},
            json={"confirm": True},
        )

    assert configured.status_code == 200
    assert "requestBody" not in openapi.json()["paths"]["/v1/connectors/configure"]["post"]
    assert "/v1/connectors/{connector}/conversation-access" not in openapi.json()["paths"]
    assert listed.json()[0]["connected"] is True
    catalog_fields = {
        key: listed.json()[0][key]
        for key in (
            "category",
            "toolkit",
            "auto_fetch_supported",
            "conversation_tools_supported",
            "oauth_setup",
        )
    }
    assert catalog_fields == {
        "category": "development",
        "toolkit": "github",
        "auto_fetch_supported": True,
        "conversation_tools_supported": True,
        "oauth_setup": "managed",
    }
    assert handoff.json()["connect_url"].startswith("https://connect.composio.dev/")
    assert refreshed.json()["phase"] == "active"
    assert settings.status_code == 204
    assert synced.json()["items"] == []
    assert disconnected.status_code == 204
    assert calls[0] == ("configure", None)


async def test_disconnect_requires_explicit_confirmation(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/connectors/github/disconnect", json={"confirm": False})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "explicit_confirmation_required"


async def test_composio_failures_are_typed_and_never_expose_secret_or_upstream_body(
    tmp_path: Path, monkeypatch
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))

    async def reject(_service: ConnectorService) -> None:
        raise ComposioGatewayError(ComposioErrorCode.AUTH)

    monkeypatch.setattr(ConnectorService, "configure", reject)
    transport = ASGITransport(app=create_app(container=container))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/connectors/configure")

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "connector_broker_auth", "retryable": False}}


async def test_missing_byo_auth_config_is_a_typed_conflict(tmp_path: Path, monkeypatch) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))

    async def reject(
        _service: ConnectorService,
        _workspace_id: str,
        _connector: ConnectorKind,
    ) -> ConnectHandoff:
        raise ComposioGatewayError(ComposioErrorCode.AUTH_CONFIG_REQUIRED)

    monkeypatch.setattr(ConnectorService, "connect", reject)
    transport = ASGITransport(app=create_app(container=container))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/connectors/trello/connect")

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "connector_broker_auth_config_required",
            "retryable": False,
        }
    }
