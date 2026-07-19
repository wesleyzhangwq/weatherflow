from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from weatherflow.activity import (
    ActivityWatchClient,
    ActivityWatchFallbackPurpose,
    ActivityWatchProtocolError,
    ActivityWatchSQLiteFallback,
)


async def test_activitywatch_client_reads_info_buckets_events_and_query_only() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/info"):
            return httpx.Response(
                200,
                json={
                    "hostname": "WesZ-Station",
                    "version": "v0.13.1 (rust)",
                    "testing": False,
                    "device_id": "device-1",
                },
            )
        if request.url.path.endswith("/buckets"):
            return httpx.Response(
                200,
                json={
                    "aw-watcher-window_WesZ-Station": {
                        "id": "aw-watcher-window_WesZ-Station",
                        "type": "currentwindow",
                        "client": "aw-watcher-window",
                        "hostname": "WesZ-Station",
                        "created": "2026-07-16T09:07:49Z",
                        "data": {},
                        "metadata": {
                            "start": "2026-07-16T09:07:49Z",
                            "end": "2026-07-16T12:08:36Z",
                        },
                    }
                },
            )
        if "/events" in request.url.path:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 304,
                        "timestamp": "2026-07-16T12:06:42Z",
                        "duration": 134.48,
                        "data": {"app": "ChatGPT", "title": "ChatGPT"},
                    }
                ],
            )
        if request.url.path.endswith("/query/"):
            assert json.loads(request.content) == {
                "timeperiods": ["2026-07-16T00:00:00+00:00/2026-07-16T01:00:00+00:00"],
                "query": ["RETURN = [];"],
            }
            return httpx.Response(200, json=[[]])
        raise AssertionError(request.url)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:5600/api/0",
    ) as http:
        client = ActivityWatchClient(http=http)
        info = await client.info()
        buckets = await client.buckets()
        events = await client.events(
            "aw-watcher-window_WesZ-Station",
            start=datetime(2026, 7, 16, 0, tzinfo=UTC),
            end=datetime(2026, 7, 16, 1, tzinfo=UTC),
        )
        result = await client.query(
            start=datetime(2026, 7, 16, 0, tzinfo=UTC),
            end=datetime(2026, 7, 16, 1, tzinfo=UTC),
            statements=("RETURN = [];",),
        )

    assert info.version == "v0.13.1 (rust)"
    assert buckets[0].metadata.end == datetime(2026, 7, 16, 12, 8, 36, tzinfo=UTC)
    assert events[0].bucket_id == "aw-watcher-window_WesZ-Station"
    assert events[0].data == {"app": "ChatGPT", "title": "ChatGPT"}
    assert result == [[]]
    assert [request.method for request in requests] == ["GET", "GET", "GET", "POST"]
    assert requests[-1].url.path.endswith("/query/")


async def test_activitywatch_classes_prefers_classes_endpoint_and_falls_back_to_settings() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/settings/classes"):
            return httpx.Response(404)
        if request.url.path.endswith("/settings"):
            return httpx.Response(
                200,
                json={
                    "classes": [
                        {
                            "name": ["Work", "Programming"],
                            "rule": {"type": "regex", "regex": "GitHub|vim"},
                        }
                    ]
                },
            )
        raise AssertionError(request.url)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:5600/api/0",
    ) as http:
        rules = await ActivityWatchClient(http=http).classes()

    assert rules == [
        {
            "name": ["Work", "Programming"],
            "rule": {"type": "regex", "regex": "GitHub|vim"},
        }
    ]
    assert paths == ["/api/0/settings/classes", "/api/0/settings"]


async def test_discovery_range_includes_rotated_hosts_but_not_unrelated_buckets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/info"):
            return httpx.Response(
                200,
                json={"hostname": "current-host", "version": "v0.13.1"},
            )
        if request.url.path.endswith("/buckets"):
            return httpx.Response(
                200,
                json={
                    "window-current": {
                        "id": "window-current",
                        "type": "currentwindow",
                        "client": "aw-watcher-window",
                        "hostname": "current-host",
                        "metadata": {
                            "start": "2026-07-15T00:00:00Z",
                            "end": "2026-07-16T00:00:00Z",
                        },
                    },
                    "afk-current": {
                        "id": "afk-current",
                        "type": "afkstatus",
                        "client": "aw-watcher-afk",
                        "hostname": "current-host",
                        "metadata": {
                            "start": "2026-07-15T00:00:00Z",
                            "end": "2026-07-16T00:00:00Z",
                        },
                    },
                    "window-old": {
                        "id": "window-old",
                        "type": "currentwindow",
                        "client": "aw-watcher-window",
                        "hostname": "old-host",
                        "metadata": {
                            "start": "2026-07-01T00:00:00Z",
                            "end": "2026-07-14T23:59:00Z",
                        },
                    },
                    "afk-old": {
                        "id": "afk-old",
                        "type": "afkstatus",
                        "client": "aw-watcher-afk",
                        "hostname": "old-host",
                        "metadata": {
                            "start": "2026-07-01T00:00:00Z",
                            "end": "2026-07-14T23:59:00Z",
                        },
                    },
                    "stopwatch": {
                        "id": "stopwatch",
                        "type": "stopwatch",
                        "client": "aw-stopwatch",
                        "hostname": "current-host",
                        "metadata": {
                            "start": "2020-01-01T00:00:00Z",
                            "end": "2026-07-16T01:00:00Z",
                        },
                    },
                    "web-ancient": {
                        "id": "web-ancient",
                        "type": "web.tab.current",
                        "client": "aw-watcher-web",
                        "hostname": "current-host",
                        "metadata": {
                            "start": "2019-01-01T00:00:00Z",
                            "end": "2026-07-16T01:00:00Z",
                        },
                    },
                },
            )
        if request.url.path.endswith("/settings/classes"):
            return httpx.Response(200, json=[])
        if request.url.path.endswith("/settings"):
            return httpx.Response(200, json={"classes": []})
        raise AssertionError(request.url)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:5600/api/0",
    ) as http:
        discovery = await ActivityWatchClient(http=http).discover()

    assert discovery.data_start == datetime(2026, 7, 1, tzinfo=UTC)
    assert discovery.data_end == datetime(2026, 7, 16, tzinfo=UTC)


def test_activitywatch_client_rejects_non_loopback_or_non_api_base() -> None:
    with pytest.raises(ActivityWatchProtocolError):
        ActivityWatchClient(base_url="https://activity.example/api/0")
    with pytest.raises(ActivityWatchProtocolError):
        ActivityWatchClient(base_url="http://127.0.0.1:5600/api/1")


async def test_sqlite_fallback_is_short_lived_and_query_only(tmp_path: Path) -> None:
    path = tmp_path / "activitywatch.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE facts(id INTEGER PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO facts(value) VALUES ('ok')")
    connection.commit()
    connection.close()
    fallback = ActivityWatchSQLiteFallback(path)

    rows = await fallback.query_rows(
        "SELECT id, value FROM facts",
        purpose=ActivityWatchFallbackPurpose.DIAGNOSTIC,
    )

    assert rows == [{"id": 1, "value": "ok"}]
    with pytest.raises(ActivityWatchProtocolError):
        await fallback.query_rows(
            "DELETE FROM facts",
            purpose=ActivityWatchFallbackPurpose.DIAGNOSTIC,
        )
