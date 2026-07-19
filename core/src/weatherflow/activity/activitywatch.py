from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import httpx

from weatherflow.activity.categories import category_rule_version
from weatherflow.activity.models import (
    ActivityWatchBucket,
    ActivityWatchDiscovery,
    ActivityWatchEvent,
    ActivityWatchFallbackPurpose,
    ActivityWatchInfo,
    ActivityWatchProtocolError,
    ActivityWatchUnavailable,
    require_aware,
)

DEFAULT_ACTIVITYWATCH_API = "http://127.0.0.1:5600/api/0"
DEFAULT_ACTIVITYWATCH_DATABASE = (
    Path.home()
    / "Library"
    / "Application Support"
    / "activitywatch"
    / "aw-server-rust"
    / "sqlite.db"
)


class ActivityWatchReadClient(Protocol):
    async def info(self) -> ActivityWatchInfo: ...

    async def buckets(self) -> list[ActivityWatchBucket]: ...

    async def events(
        self,
        bucket_id: str,
        *,
        start,
        end,
        limit: int = 5_000,
    ) -> list[ActivityWatchEvent]: ...

    async def settings(self) -> dict[str, Any]: ...

    async def classes(self) -> list[dict[str, Any]]: ...

    async def query(
        self,
        *,
        start,
        end,
        statements: Sequence[str],
    ) -> list[Any]: ...

    async def discover(self) -> ActivityWatchDiscovery: ...

    async def close(self) -> None: ...


class ActivityWatchClient:
    """Strictly read-only ActivityWatch loopback REST client.

    The ordinary surface contains GET-only reads and ActivityWatch's
    semantically read-only ``POST /query/`` operation. There are intentionally
    no bucket, event, settings, lifecycle, or retention mutation methods.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_ACTIVITYWATCH_API,
        http: httpx.AsyncClient | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        effective = str(http.base_url).rstrip("/") if http is not None else base_url.rstrip("/")
        self._validate_base_url(effective)
        self.base_url = effective
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=f"{effective}/",
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
        )

    async def __aenter__(self) -> ActivityWatchClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def info(self) -> ActivityWatchInfo:
        payload = await self._get_json("/info")
        if not isinstance(payload, Mapping):
            raise ActivityWatchProtocolError("ActivityWatch info response must be an object")
        return ActivityWatchInfo.model_validate(payload)

    async def buckets(self) -> list[ActivityWatchBucket]:
        payload = await self._get_json("/buckets")
        if isinstance(payload, Mapping):
            candidates = []
            for bucket_id, value in payload.items():
                if not isinstance(value, Mapping):
                    raise ActivityWatchProtocolError(
                        "ActivityWatch bucket response contains a non-object"
                    )
                candidate = dict(value)
                candidate.setdefault("id", str(bucket_id))
                candidates.append(candidate)
        elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
            candidates = list(payload)
        else:
            raise ActivityWatchProtocolError("ActivityWatch buckets response is invalid")
        return sorted(
            (ActivityWatchBucket.model_validate(item) for item in candidates),
            key=lambda bucket: bucket.id,
        )

    async def events(
        self,
        bucket_id: str,
        *,
        start,
        end,
        limit: int = 5_000,
    ) -> list[ActivityWatchEvent]:
        if not bucket_id or "/" in bucket_id or "\x00" in bucket_id:
            raise ValueError("invalid ActivityWatch bucket id")
        window_start = require_aware(start)
        window_end = require_aware(end)
        if window_end <= window_start:
            raise ValueError("end must be after start")
        if limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        payload = await self._get_json(
            f"/buckets/{quote(bucket_id, safe='')}/events",
            params={
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
                "limit": limit,
            },
        )
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            raise ActivityWatchProtocolError("ActivityWatch events response must be a list")
        return [
            ActivityWatchEvent.model_validate({**dict(item), "bucket_id": bucket_id})
            for item in payload
            if isinstance(item, Mapping)
        ]

    async def settings(self) -> dict[str, Any]:
        payload = await self._get_json("/settings")
        if not isinstance(payload, Mapping):
            raise ActivityWatchProtocolError("ActivityWatch settings response must be an object")
        return dict(payload)

    async def classes(self) -> list[dict[str, Any]]:
        response = await self._request("GET", "/settings/classes", allow_not_found=True)
        if response is not None:
            payload = self._decode_json(response)
            if isinstance(payload, Mapping):
                payload = payload.get("classes", [])
            if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
                raise ActivityWatchProtocolError("ActivityWatch classes response must be a list")
            return [dict(item) for item in payload if isinstance(item, Mapping)]
        settings = await self.settings()
        payload = settings.get("classes", [])
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            raise ActivityWatchProtocolError("ActivityWatch settings classes must be a list")
        return [dict(item) for item in payload if isinstance(item, Mapping)]

    async def query(
        self,
        *,
        start,
        end,
        statements: Sequence[str],
    ) -> list[Any]:
        window_start = require_aware(start)
        window_end = require_aware(end)
        if window_end <= window_start:
            raise ValueError("end must be after start")
        if not statements or len(statements) > 32:
            raise ValueError("query requires between 1 and 32 fixed statements")
        if any(not isinstance(statement, str) or not statement.strip() for statement in statements):
            raise ValueError("query statements must be non-empty strings")
        response = await self._request(
            "POST",
            "/query/",
            json={
                "timeperiods": [f"{window_start.isoformat()}/{window_end.isoformat()}"],
                "query": list(statements),
            },
        )
        assert response is not None
        payload = self._decode_json(response)
        if not isinstance(payload, list):
            raise ActivityWatchProtocolError("ActivityWatch query response must be a list")
        return payload

    async def discover(self) -> ActivityWatchDiscovery:
        info, buckets = await asyncio.gather(self.info(), self.buckets())
        try:
            settings = await self.settings()
        except ActivityWatchProtocolError:
            settings = {}
        rules = await self.classes()
        paired_ranges = self._paired_activity_ranges(buckets)
        starts = [start for start, _end in paired_ranges]
        ends = [end for _start, end in paired_ranges if end is not None]
        return ActivityWatchDiscovery(
            info=info,
            buckets=tuple(buckets),
            data_start=min(starts) if starts else None,
            data_end=max(ends) if ends else None,
            settings=settings,
            category_rules=category_rule_version(rules),
        )

    @staticmethod
    def _activity_fact_kind(bucket: ActivityWatchBucket) -> str | None:
        identity = " ".join((bucket.id, bucket.type, bucket.client)).casefold()
        if "afk" in identity:
            return "afk"
        if "currentwindow" in identity or "watcher-window" in identity:
            return "window"
        return None

    @classmethod
    def _paired_activity_ranges(
        cls,
        buckets: list[ActivityWatchBucket],
    ) -> list[tuple[datetime, datetime | None]]:
        ranges: list[tuple[datetime, datetime | None]] = []
        for hostname in {bucket.hostname for bucket in buckets}:
            windows = [
                bucket
                for bucket in buckets
                if bucket.hostname == hostname and cls._activity_fact_kind(bucket) == "window"
            ]
            afks = [
                bucket
                for bucket in buckets
                if bucket.hostname == hostname and cls._activity_fact_kind(bucket) == "afk"
            ]
            for window in windows:
                for afk in afks:
                    starts = [
                        value
                        for value in (
                            window.metadata.start or window.created,
                            afk.metadata.start or afk.created,
                        )
                        if value is not None
                    ]
                    if not starts:
                        continue
                    segment_start = max(starts)
                    segment_ends = [
                        value
                        for value in (
                            window.metadata.end,
                            afk.metadata.end,
                        )
                        if value is not None
                    ]
                    segment_end = min(segment_ends) if segment_ends else None
                    if segment_end is None or segment_end > segment_start:
                        ranges.append((segment_start, segment_end))
        return ranges

    async def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        response = await self._request("GET", path, params=params)
        assert response is not None
        return self._decode_json(response)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        allow_not_found: bool = False,
    ) -> httpx.Response | None:
        if method not in {"GET", "POST"}:
            raise ActivityWatchProtocolError("ActivityWatch client is read-only")
        if method == "POST" and path != "/query/":
            raise ActivityWatchProtocolError("only ActivityWatch /query/ accepts POST")
        try:
            response = await self._http.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=json,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ActivityWatchUnavailable("ActivityWatch is unavailable") from exc
        if allow_not_found and response.status_code == 404:
            return None
        if response.status_code >= 500:
            raise ActivityWatchUnavailable("ActivityWatch is unavailable")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ActivityWatchProtocolError(
                f"ActivityWatch returned HTTP {response.status_code}"
            ) from exc
        return response

    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise ActivityWatchProtocolError("ActivityWatch returned invalid JSON") from exc

    @staticmethod
    def _validate_base_url(value: str) -> None:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port != 5600
            or parsed.path.rstrip("/") != "/api/0"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ActivityWatchProtocolError(
                "ActivityWatch base URL must be http://127.0.0.1:5600/api/0"
            )


class ActivityWatchSQLiteFallback:
    """Explicit, short-lived, query-only diagnostic access to aw-server SQLite."""

    def __init__(self, path: Path = DEFAULT_ACTIVITYWATCH_DATABASE) -> None:
        self.path = path

    async def query_rows(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
        *,
        purpose: ActivityWatchFallbackPurpose,
        max_rows: int = 10_000,
    ) -> list[dict[str, Any]]:
        if purpose not in set(ActivityWatchFallbackPurpose):
            raise ValueError("an explicit ActivityWatch fallback purpose is required")
        if max_rows < 1 or max_rows > 100_000:
            raise ValueError("max_rows must be between 1 and 100000")
        statement = sql.strip()
        first = statement.split(None, 1)[0].casefold() if statement else ""
        if first not in {"select", "with", "pragma"}:
            raise ActivityWatchProtocolError("SQLite fallback accepts read queries only")
        if ";" in statement.rstrip(";"):
            raise ActivityWatchProtocolError("SQLite fallback accepts one statement")
        return await asyncio.to_thread(
            self._query_rows_sync,
            statement,
            tuple(parameters),
            max_rows,
        )

    def _query_rows_sync(
        self,
        sql: str,
        parameters: tuple[Any, ...],
        max_rows: int,
    ) -> list[dict[str, Any]]:
        database_uri = f"file:{quote(str(self.path), safe='/')}?mode=ro"
        connection = sqlite3.connect(database_uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            cursor = connection.execute(sql, parameters)
            rows = cursor.fetchmany(max_rows + 1)
            if len(rows) > max_rows:
                raise ActivityWatchProtocolError(
                    "SQLite fallback result exceeded its explicit row bound"
                )
            return [dict(row) for row in rows]
        except sqlite3.DatabaseError as exc:
            raise ActivityWatchProtocolError(
                "ActivityWatch SQLite schema or query is unsupported"
            ) from exc
        finally:
            connection.close()
