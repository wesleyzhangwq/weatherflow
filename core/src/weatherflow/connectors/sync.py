import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from weatherflow.connectors.composio import (
    ComposioErrorCode,
    ComposioGatewayError,
)
from weatherflow.connectors.models import (
    CONNECTOR_DEFINITIONS,
    ConnectionPhase,
    ConnectorKind,
    ConnectorSnapshot,
    SourceItem,
)
from weatherflow.connectors.repository import ConnectorRepository
from weatherflow.connectors.tools import sanitize_untrusted_text, sanitize_untrusted_url
from weatherflow.events import Actor, Event, EventLedger, Sensitivity
from weatherflow.extensions import CredentialUnavailableError


class ReadGateway(Protocol):
    async def execute_read_action(
        self,
        *,
        action: str,
        connected_account_id: str,
        user_id: str,
        arguments: dict[str, Any],
    ) -> Any: ...


@dataclass(frozen=True)
class _FetchBatch:
    raw_count: int
    normalized_count: int
    items: tuple[SourceItem, ...]


class ConnectorSyncService:
    def __init__(
        self,
        *,
        repository: ConnectorRepository,
        ledger: EventLedger,
        gateway: ReadGateway,
        user_id: str,
        now: Callable[[], datetime] | None = None,
        timezone: str = "UTC",
        broker_lock: asyncio.Lock | None = None,
    ) -> None:
        self.repository = repository
        self.ledger = ledger
        self.gateway = gateway
        self.user_id = user_id
        self.now = now or (lambda: datetime.now(UTC))
        self.timezone = timezone
        self.broker_lock = broker_lock or asyncio.Lock()

    async def sync(self, workspace_id: str, connector: ConnectorKind) -> ConnectorSnapshot:
        async with self.broker_lock:
            return await self._sync_locked(workspace_id, connector)

    async def _sync_locked(
        self,
        workspace_id: str,
        connector: ConnectorKind,
        *,
        scheduled_at: datetime | None = None,
    ) -> ConnectorSnapshot:
        if not CONNECTOR_DEFINITIONS[connector].auto_fetch_supported:
            raise LookupError(f"automatic fetch unsupported: {connector.value}")
        binding = await self.repository.get_binding(workspace_id, connector)
        if scheduled_at is not None and (
            binding is None
            or not binding.enabled
            or not binding.auto_fetch_enabled
            or binding.next_sync_at > scheduled_at
        ):
            raise LookupError(f"connector binding no longer due: {connector.value}")
        if binding is None or not binding.enabled:
            raise LookupError(f"connector binding unavailable: {connector.value}")
        account = await self.repository.get_account_by_id(workspace_id, binding.account_id)
        if account is None or account.phase is not ConnectionPhase.ACTIVE:
            raise LookupError(f"connector account unavailable: {connector.value}")
        observed = scheduled_at or self.now()
        try:
            batch = await self._fetch(
                connector,
                connected_account_id=account.external_account_id,
                observed=observed,
            )
            if batch.raw_count > 0 and batch.normalized_count == 0:
                raise ValueError("provider rows could not be normalized")
        except CredentialUnavailableError:
            raise
        except ComposioGatewayError as error:
            committed = await self.repository.commit_sync_if_current(
                previous=binding,
                updated=binding.after_sync(now=observed, error_code=error.code.value),
                snapshot=None,
            )
            if not committed:
                await self._discard_changed_sync(connector, workspace_id)
            await self._event(
                "connector.sync_failed",
                connector,
                workspace_id,
                {"error_code": error.code.value, "retryable": error.retryable},
            )
            raise
        except Exception as error:
            error_code = "invalid_response"
            committed = await self.repository.commit_sync_if_current(
                previous=binding,
                updated=binding.after_sync(now=observed, error_code=error_code),
                snapshot=None,
            )
            if not committed:
                await self._discard_changed_sync(connector, workspace_id)
            await self._event(
                "connector.sync_failed",
                connector,
                workspace_id,
                {"error_code": error_code, "retryable": False},
            )
            raise ComposioGatewayError(ComposioErrorCode.UPSTREAM) from error
        snapshot = ConnectorSnapshot(
            workspace_id=workspace_id,
            connector=connector,
            fetched_at=observed,
            expires_at=observed + timedelta(minutes=binding.interval_minutes * 2),
            raw_item_count=batch.raw_count,
            normalized_item_count=batch.normalized_count,
            items=batch.items,
        )
        committed = await self.repository.commit_sync_if_current(
            previous=binding,
            updated=binding.after_sync(now=observed),
            snapshot=snapshot,
        )
        if not committed:
            await self._discard_changed_sync(connector, workspace_id)
        await self._event(
            "connector.synced",
            connector,
            workspace_id,
            {
                "item_count": len(snapshot.items),
                "source_id_digests": [
                    hashlib.sha256(item.source_id.encode()).hexdigest() for item in snapshot.items
                ],
                "fetched_at": observed.isoformat(),
            },
        )
        return snapshot

    async def _discard_changed_sync(
        self,
        connector: ConnectorKind,
        workspace_id: str,
    ) -> None:
        await self._event(
            "connector.sync_discarded",
            connector,
            workspace_id,
            {"reason": "binding_changed"},
        )
        raise LookupError(f"connector binding changed during sync: {connector.value}")

    async def sync_due(self) -> list[ConnectorSnapshot]:
        snapshots: list[ConnectorSnapshot] = []
        observed = self.now()
        for binding in await self.repository.list_due_bindings(observed):
            try:
                async with self.broker_lock:
                    snapshots.append(
                        await self._sync_locked(
                            binding.workspace_id,
                            binding.connector,
                            scheduled_at=observed,
                        )
                    )
            except (ComposioGatewayError, LookupError):
                continue
        return snapshots

    async def _fetch(
        self,
        connector: ConnectorKind,
        *,
        connected_account_id: str,
        observed: datetime,
    ) -> _FetchBatch:
        definition = CONNECTOR_DEFINITIONS[connector]
        if connector is ConnectorKind.GITHUB:
            profile = await self.gateway.execute_read_action(
                action=definition.read_actions[0],
                connected_account_id=connected_account_id,
                user_id=self.user_id,
                arguments={},
            )
            login = _find_string(profile, ("login", "username"))
            if login is None:
                raise ValueError("GitHub profile did not contain a login")
            overlap_start = observed - timedelta(days=7)
            notifications = await self.gateway.execute_read_action(
                action=definition.read_actions[1],
                connected_account_id=connected_account_id,
                user_id=self.user_id,
                arguments={
                    "all": False,
                    "participating": False,
                    "since": overlap_start.isoformat(),
                    "per_page": 50,
                    "page": 1,
                },
            )
            activity = await self.gateway.execute_read_action(
                action=definition.read_actions[2],
                connected_account_id=connected_account_id,
                user_id=self.user_id,
                arguments={
                    "q": (f"author:{login} committer-date:>={overlap_start.date().isoformat()}"),
                    "sort": "committer-date",
                    "order": "desc",
                    "per_page": 50,
                    "page": 1,
                },
            )
            rows = [
                *_required_item_rows(notifications),
                *_required_item_rows(activity),
            ]
        elif connector is ConnectorKind.GMAIL:
            data = await self.gateway.execute_read_action(
                action=definition.read_actions[0],
                connected_account_id=connected_account_id,
                user_id=self.user_id,
                arguments={
                    "query": "is:unread newer_than:30d -in:spam -in:trash",
                    "max_results": 50,
                    "include_payload": False,
                },
            )
            rows = _required_item_rows(data)
        elif connector is ConnectorKind.GOOGLE_CALENDAR:
            local_start = observed.astimezone(ZoneInfo(self.timezone)).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            data = await self.gateway.execute_read_action(
                action=definition.read_actions[0],
                connected_account_id=connected_account_id,
                user_id=self.user_id,
                arguments={
                    "time_min": (local_start - timedelta(days=7)).isoformat(),
                    "time_max": (local_start + timedelta(days=14)).isoformat(),
                    "single_events": True,
                    "show_deleted": False,
                    "max_results_per_calendar": 20,
                },
            )
            rows = _required_item_rows(data)
        else:
            raise LookupError(f"automatic fetch unsupported: {connector.value}")
        normalized: list[SourceItem] = []
        seen_ids: set[str] = set()
        normalized_count = 0
        bounded_rows = rows[:100]
        for raw in bounded_rows:
            if not isinstance(raw, dict):
                continue
            item = _normalize_item(
                connector,
                raw,
                observed,
                timezone=self.timezone,
            )
            if item is None:
                continue
            normalized_count += 1
            if item.source_id in seen_ids:
                continue
            normalized.append(item)
            seen_ids.add(item.source_id)
        return _FetchBatch(
            raw_count=len(bounded_rows),
            normalized_count=normalized_count,
            items=tuple(normalized),
        )

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
    _recognized, rows = _extract_item_rows(value)
    return [row for row in rows if isinstance(row, dict)]


def _required_item_rows(value: Any) -> list[Any]:
    recognized, rows = _extract_item_rows(value)
    if not recognized:
        raise ValueError("provider response did not contain a recognized item envelope")
    return rows


def _extract_item_rows(value: Any) -> tuple[bool, list[Any]]:
    if isinstance(value, list):
        return True, list(value)
    if not isinstance(value, dict):
        return False, []
    if not value:
        return False, []
    for key in ("items", "messages", "events", "results", "notifications"):
        if key not in value:
            continue
        rows = value[key]
        if isinstance(rows, list):
            return True, list(rows)
        return False, []
    if "data" in value:
        return _extract_item_rows(value["data"])
    return False, []


def _normalize_item(
    connector: ConnectorKind,
    raw: dict[str, Any],
    observed: datetime,
    *,
    timezone: str = "UTC",
) -> SourceItem | None:
    source_id = _find_string(
        raw,
        (
            "id",
            "sha",
            "messageId",
            "message_id",
            "threadId",
            "thread_id",
            "node_id",
        ),
    )
    if source_id is None:
        numeric_id = raw.get("id")
        if isinstance(numeric_id, int):
            source_id = str(numeric_id)
    if not source_id:
        return None
    ends_at = None
    if connector is ConnectorKind.GMAIL:
        title = _find_string(raw, ("subject", "title")) or "未读邮件"
        preview = raw.get("preview")
        summary = (
            (_find_string(preview, ("body",)) if isinstance(preview, dict) else None)
            or _find_string(raw, ("snippet",))
            or ""
        )
        occurred = _parse_datetime_value(
            _find_string(raw, ("messageTimestamp", "date", "internal_date", "received_at"))
        )
        if occurred is None:
            return None
    elif connector is ConnectorKind.GOOGLE_CALENDAR:
        title = _find_string(raw, ("summary", "title")) or "日程"
        summary = _find_string(raw, ("description", "location")) or ""
        start = raw.get("start")
        start_value = _find_string(start, ("dateTime", "date")) if isinstance(start, dict) else None
        end = raw.get("end")
        end_value = _find_string(end, ("dateTime", "date")) if isinstance(end, dict) else None
        local_timezone = ZoneInfo(timezone)
        occurred = _parse_datetime_value(start_value, default_timezone=local_timezone)
        if occurred is None:
            return None
        ends_at = (
            _parse_datetime_value(end_value, default_timezone=local_timezone)
            if end_value is not None
            else None
        )
        if end_value is not None and ends_at is None:
            return None
        if ends_at is not None and ends_at < occurred:
            return None
    else:
        title = _find_string(raw, ("title", "name", "message")) or "GitHub 活动"
        summary = _find_string(raw, ("body", "summary", "state", "reason", "type", "message")) or ""
        occurred = _parse_datetime(
            _find_string(raw, ("updated_at", "created_at", "date")), observed
        )
    return SourceItem(
        source_id=sanitize_untrusted_text(source_id[:500]),
        occurred_at=occurred,
        ends_at=ends_at,
        title=sanitize_untrusted_text(title[:500]),
        summary=sanitize_untrusted_text(summary[:2_000]),
        url=(
            sanitize_untrusted_url(url)
            if (
                url := _find_string(
                    raw,
                    ("html_url", "htmlLink", "display_url", "url"),
                )
            )
            is not None
            else None
        ),
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


def _parse_datetime(
    value: str | None,
    fallback: datetime,
    *,
    default_timezone: ZoneInfo | None = None,
) -> datetime:
    return _parse_datetime_value(value, default_timezone=default_timezone) or fallback


def _parse_datetime_value(
    value: str | None,
    *,
    default_timezone: ZoneInfo | None = None,
) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_timezone or UTC)
    return parsed
