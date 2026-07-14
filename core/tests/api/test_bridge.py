import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.events import Actor, Event


def test_configured_bridge_token_gates_http_and_websocket(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, bridge_token="launch-secret")
    with asyncio.Runner() as runner:
        container = runner.run(RuntimeContainer.create(settings))
        event = Event.new(
            type="test.event",
            actor=Actor.SYSTEM,
            stream_kind="test",
            stream_id="1",
            correlation_id="1",
            payload={},
        )
        runner.run(container.ledger.append(event))
        with TestClient(create_app(settings, container=container)) as client:
            assert client.get("/health").status_code == 401
            assert (
                client.get("/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
            )
            assert (
                client.get("/health", headers={"Authorization": "Bearer launch-secret"}).status_code
                == 200
            )

            preflight = client.options(
                "/v1/desktop/snapshot",
                headers={
                    "Origin": "http://localhost:1421",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
            assert preflight.status_code == 200
            assert preflight.headers["access-control-allow-origin"] == "http://localhost:1421"
            assert "authorization" in preflight.headers["access-control-allow-headers"].lower()

            protocols = ["weatherflow-v1", "weatherflow-auth.launch-secret"]
            with client.websocket_connect("/v1/events", subprotocols=protocols) as websocket:
                received = websocket.receive_json()
                assert received["id"] == event.id
                assert received["type"] == "test.event"
                assert websocket.accepted_subprotocol == "weatherflow-v1"

            with pytest.raises(WebSocketDisconnect) as unauthorized:
                with client.websocket_connect(
                    "/v1/events", subprotocols=["weatherflow-v1", "weatherflow-auth.wrong"]
                ):
                    pass
            assert unauthorized.value.code == 4401

            with pytest.raises(WebSocketDisconnect) as invalid_cursor:
                with client.websocket_connect(
                    "/v1/events?cursor=missing", subprotocols=protocols
                ) as websocket:
                    websocket.receive_json()
            assert invalid_cursor.value.code == 4409

        events = runner.run(container.ledger.list_after(None, limit=1000))
        assert "launch-secret" not in "".join(event.model_dump_json() for event in events)


def test_unconfigured_development_bridge_remains_usable(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    with asyncio.Runner() as runner:
        container = runner.run(RuntimeContainer.create(settings))
        with TestClient(create_app(settings, container=container)) as client:
            assert client.get("/health").status_code == 200


def test_event_socket_observes_disconnects_during_idle_polling() -> None:
    source = (Path(__file__).parents[2] / "src" / "weatherflow" / "api" / "app.py").read_text()
    assert "await asyncio.wait_for(websocket.receive(), timeout=0.25)" in source
