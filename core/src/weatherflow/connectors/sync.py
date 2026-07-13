from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

from weatherflow.connectors.composio import ComposioGatewayError
from weatherflow.connectors.models import (
    CONNECTOR_DEFINITIONS,
    ConnectionPhase,
    ConnectorKind,
    ConnectorSnapshot,
    SourceItem,
)
from weatherflow.connectors.repository import ConnectorRepository
from weatherflow.events import Actor, Event, EventLedger, Sensitivity


class ReadGateway(Protocol):
    async def execute_read_action(
        self,
        *,
        action: str,
        connected_account_id: str,
        arguments: dict[str, Any],
    ) -> Any: ...


class ConnectorSyncService:
    def __init__(
        self,
        *,
        repository: ConnectorRepository,
        ledger: EventLedger,
        gateway: ReadGateway,
        now: Callable[[], datetime] | None = None,
        timezone: str = "UTC",
    ) -> None:
        self.repository = repository
        self.ledger = ledger
        self.gateway = gateway
        self.now = now or (lambda: datetime.now(UTC))
        self.timezone = timezone

    async def sync(self, workspace_id: str, connector: ConnectorKind) -> ConnectorSnapshot:
        binding = await self.repository.get_binding(workspace_id, connector)
        if binding is None or not binding.enabled:
            raise LookupError(f"connector binding unavailable: {connector.value}")
        account = await self.repository.get_account_by_id(binding.account_id)
        if account is None or account.phase is not ConnectionPhase.ACTIVE:
            raise LookupError(f"connector account unavailable: {connector.value}")
        observed = self.now()
        try:
            raw_items = await self._fetch(
                connector,
                connected_account_id=account.external_account_id,
                observed=observed,
            )
        except ComposioGatewayError as error:
            await self.repository.save_binding(
                binding.after_sync(now=observed, error_code=error.code.value)
            )
            await self._event(
                "connector.sync_failed",
                connector,
                workspace_id,
                {"error_code": error.code.value, "retryable": error.retryable},
            )
            raise
        snapshot = ConnectorSnapshot(
            workspace_id=workspace_id,
            connector=connector,
            fetched_at=observed,
            expires_at=observed + timedelta(minutes=binding.interval_minutes * 2),
            items=tuple(raw_items[:100]),
        )
        await self.repository.replace_snapshot(snapshot)
        await self.repository.save_binding(binding.after_sync(now=observed))
        await self._event(
            "connector.synced",
            connector,
            workspace_id,
            {
                "item_count": len(snapshot.items),
                "source_ids": [item.source_id for item in snapshot.items],
                "fetched_at": observed.isoformat(),
            },
        )
        return snapshot

    async def sync_due(self) -> list[ConnectorSnapshot]:
        snapshots: list[ConnectorSnapshot] = []
        for binding in await self.repository.list_due_bindings(self.now()):
            try:
                snapshots.append(await self.sync(binding.workspace_id, binding.connector))
            except (ComposioGatewayError, LookupError):
                continue
        return snapshots

    async def _fetch(
        self,
        connector: ConnectorKind,
        *,
        connected_account_id: str,
        observed: datetime,
    ) -> list[SourceItem]:
        definition = CONNECTOR_DEFINITIONS[connector]
        if connector is ConnectorKind.GITHUB:
            profile = await self.gateway.execute_read_action(
                action=definition.read_actions[0],
                connected_account_id=connected_account_id,
                arguments={},
            )
            login = _find_string(profile, ("login", "username"))
            if login is None:
                raise ValueError("GitHub profile did not contain a login")
            data = await self.gateway.execute_read_action(
                action=definition.read_actions[1],
                connected_account_id=connected_account_id,
                arguments={
                    "q": f"involves:{login} updated:>{(observed - timedelta(days=7)).date()}",
                    "sort": "updated",
                    "order": "desc",
                    "per_page": 50,
                    "page": 1,
                },
            )
        elif connector is ConnectorKind.GMAIL:
            data = await self.gateway.execute_read_action(
                action=definition.read_actions[0],
                connected_account_id=connected_account_id,
                arguments={
                    "query": "is:unread -in:spam -in:trash",
                    "max_results": 50,
                },
            )
        else:
            data = await self.gateway.execute_read_action(
                action=definition.read_actions[0],
                connected_account_id=connected_account_id,
                arguments={
                    "timeMin": observed.isoformat(),
                    "timeMax": (observed + timedelta(days=14)).isoformat(),
                    "singleEvents": True,
                    "timeZone": self.timezone,
                    "maxResults": 50,
                },
            )
        return [
            item
            for raw in _item_rows(data)[:100]
            if (item := _normalize_item(connector, raw, observed)) is not None
        ]

    async def _event(
        self,
        event_type: str,
        connector: ConnectorKind,
        workspace_id: str,
        payload: dict[str, object],
    ) -> None:
        await self.ledger.append(
            Event.new(
                type=event_type,
                actor=Actor.SYSTEM,
                stream_kind="connector",
                stream_id=connector.value,
                correlation_id=workspace_id,
                payload={"workspace_id": workspace_id, **payload},
                sensitivity=Sensitivity.PRIVATE,
            )
        )


def _item_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("items", "messages", "events", "results"):
        rows = value.get(key)
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    nested = value.get("data")
    return _item_rows(nested) if nested is not None else []


def _normalize_item(
    connector: ConnectorKind, raw: dict[str, Any], observed: datetime
) -> SourceItem | None:
    source_id = _find_string(raw, ("id", "message_id", "thread_id", "node_id"))
    if source_id is None:
        numeric_id = raw.get("id")
        if isinstance(numeric_id, int):
            source_id = str(numeric_id)
    if not source_id:
        return None
    if connector is ConnectorKind.GMAIL:
        title = _find_string(raw, ("subject", "title")) or "未读邮件"
        summary = _find_string(raw, ("snippet", "summary", "body")) or ""
        occurred = _parse_datetime(
            _find_string(raw, ("date", "internal_date", "received_at")), observed
        )
    elif connector is ConnectorKind.GOOGLE_CALENDAR:
        title = _find_string(raw, ("summary", "title")) or "日程"
        summary = _find_string(raw, ("description", "location")) or ""
        start = raw.get("start")
        start_value = _find_string(start, ("dateTime", "date")) if isinstance(start, dict) else None
        occurred = _parse_datetime(start_value, observed)
    else:
        title = _find_string(raw, ("title", "name")) or "GitHub 活动"
        summary = _find_string(raw, ("body", "summary", "state")) or ""
        occurred = _parse_datetime(_find_string(raw, ("updated_at", "created_at")), observed)
    return SourceItem(
        source_id=source_id,
        occurred_at=occurred,
        title=title[:500],
        summary=summary[:2_000],
        url=_find_string(raw, ("html_url", "htmlLink", "url")),
    )


def _find_string(value: Any, keys: tuple[str, ...]) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    for nested in value.values():
        if isinstance(nested, dict):
            candidate = _find_string(nested, keys)
            if candidate:
                return candidate
    return None


def _parse_datetime(value: str | None, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
