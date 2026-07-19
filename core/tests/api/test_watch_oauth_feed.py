from datetime import UTC, datetime, timedelta
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.connectors import (
    ConnectorFeed,
    ConnectorFeedHealth,
    ConnectorFeedItem,
    ConnectorFeedSource,
    ConnectorKind,
)


async def test_watch_oauth_feed_route_is_workspace_scoped_and_bounded(
    tmp_path: Path, monkeypatch
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    workspace_id = container.default_workspace.id
    now = datetime(2026, 7, 17, 4, tzinfo=UTC)
    calls: list[tuple[str, int]] = []

    async def get(requested_workspace_id: str, *, limit: int = 30) -> ConnectorFeed:
        calls.append((requested_workspace_id, limit))
        return ConnectorFeed(
            workspace_id=requested_workspace_id,
            generated_at=now,
            sources=(
                ConnectorFeedSource(
                    connector=ConnectorKind.GITHUB,
                    label="GitHub",
                    health=ConnectorFeedHealth.HEALTHY,
                    connected=True,
                    enabled=True,
                    stale=False,
                    item_count=1,
                    last_sync_at=now,
                    next_sync_at=now + timedelta(days=1),
                    snapshot_fetched_at=now,
                    refresh_cadence="daily",
                    fetch_strategy="github_unread_notifications_and_recent_activity",
                    coverage_past_days=7,
                    coverage_future_days=0,
                    raw_item_count=2,
                    normalized_item_count=1,
                    normalization_health="partial",
                ),
            ),
            items=(
                ConnectorFeedItem(
                    connector=ConnectorKind.GITHUB,
                    source_id="issue-1",
                    occurred_at=now,
                    title="Issue",
                    summary="Untrusted source record",
                ),
            ),
        )

    monkeypatch.setattr(container.connector_feed, "get", get)
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/v1/watch/oauth-feed",
            params={"workspace_id": workspace_id, "limit": 7},
        )

    assert response.status_code == 200
    assert calls == [(workspace_id, 7)]
    assert response.json()["items"][0]["untrusted"] is True
    assert response.json()["sources"][0] == {
        "connector": "github",
        "label": "GitHub",
        "health": "healthy",
        "connected": True,
        "enabled": True,
        "stale": False,
        "item_count": 1,
        "last_sync_at": now.isoformat().replace("+00:00", "Z"),
        "next_sync_at": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "snapshot_fetched_at": now.isoformat().replace("+00:00", "Z"),
        "refresh_cadence": "daily",
        "fetch_strategy": "github_unread_notifications_and_recent_activity",
        "coverage_past_days": 7,
        "coverage_future_days": 0,
        "raw_item_count": 2,
        "normalized_item_count": 1,
        "normalization_health": "partial",
        "last_error_code": None,
    }
    assert "account_id" not in response.text
    assert "credential" not in response.text


async def test_watch_oauth_feed_rejects_unknown_workspace_and_oversized_limit(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/v1/watch/oauth-feed", params={"workspace_id": "missing"})
        oversized = await client.get(
            "/v1/watch/oauth-feed",
            params={"workspace_id": container.default_workspace.id, "limit": 31},
        )

    assert missing.status_code == 404
    assert oversized.status_code == 422
