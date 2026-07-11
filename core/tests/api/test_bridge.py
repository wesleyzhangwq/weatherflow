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
    container = asyncio.run(RuntimeContainer.create(settings))
    event = Event.new(
        type="test.event",
        actor=Actor.SYSTEM,
        stream_kind="test",
        stream_id="1",
        correlation_id="1",
        payload={},
    )
    asyncio.run(container.ledger.append(event))
    client = TestClient(create_app(settings, container=container))

    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert (
        client.get("/health", headers={"Authorization": "Bearer launch-secret"}).status_code == 200
    )

    with client.websocket_connect("/v1/events?token=launch-secret") as websocket:
        received = websocket.receive_json()
        assert received["id"] == event.id
        assert received["type"] == "test.event"

    with pytest.raises(WebSocketDisconnect) as unauthorized:
        with client.websocket_connect("/v1/events?token=wrong"):
            pass
    assert unauthorized.value.code == 4401

    with pytest.raises(WebSocketDisconnect) as invalid_cursor:
        with client.websocket_connect("/v1/events?token=launch-secret&cursor=missing") as websocket:
            websocket.receive_json()
    assert invalid_cursor.value.code == 4409

    events = asyncio.run(container.ledger.list_after(None, limit=1000))
    assert "launch-secret" not in "".join(event.model_dump_json() for event in events)


def test_unconfigured_development_bridge_remains_usable(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    container = asyncio.run(RuntimeContainer.create(settings))
    client = TestClient(create_app(settings, container=container))

    assert client.get("/health").status_code == 200
