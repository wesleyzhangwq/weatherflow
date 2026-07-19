from collections.abc import Callable
from datetime import UTC, datetime

from weatherflow.connectors.models import (
    CONNECTOR_DEFINITIONS,
    ConnectionPhase,
    ConnectorFeed,
    ConnectorFeedHealth,
    ConnectorFeedItem,
    ConnectorFeedSource,
    ConnectorKind,
    ConnectorNormalizationHealth,
    ConnectorSnapshot,
)
from weatherflow.connectors.repository import ConnectorRepository
from weatherflow.connectors.tools import sanitize_untrusted_text, sanitize_untrusted_url

_FEED_CONNECTORS = (
    ConnectorKind.GITHUB,
    ConnectorKind.GMAIL,
    ConnectorKind.GOOGLE_CALENDAR,
)
_OAUTH_RECONNECT_ERRORS = frozenset({"auth", "project_changed"})


class ConnectorFeedService:
    """Builds a bounded, identity-free Watch projection from connector snapshots."""

    def __init__(
        self,
        *,
        repository: ConnectorRepository,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.now = now or (lambda: datetime.now(UTC))

    async def get(self, workspace_id: str, *, limit: int = 30) -> ConnectorFeed:
        if not 1 <= limit <= 30:
            raise ValueError("connector feed limit must be between 1 and 30")
        observed = self.now()
        sources: list[ConnectorFeedSource] = []
        items: list[ConnectorFeedItem] = []
        for connector in _FEED_CONNECTORS:
            definition = CONNECTOR_DEFINITIONS[connector]
            if definition.fetch_strategy is None:
                raise RuntimeError(f"missing connector fetch strategy: {connector.value}")
            binding = await self.repository.get_binding(workspace_id, connector)
            snapshot = await self.repository.get_snapshot(workspace_id, connector)
            account = (
                await self.repository.get_account_by_id(workspace_id, binding.account_id)
                if binding is not None
                else None
            )
            connected = account is not None and account.phase is ConnectionPhase.ACTIVE
            enabled = bool(
                connected and binding is not None and binding.enabled and binding.auto_fetch_enabled
            )
            stale = snapshot is not None and (
                snapshot.expires_at <= observed
                or (
                    binding is not None
                    and binding.auto_fetch_enabled
                    and binding.next_sync_at < observed
                )
            )
            health = _health(
                connected=connected,
                enabled=enabled,
                stale=stale,
                error_code=binding.last_error_code if binding is not None else None,
                has_snapshot=snapshot is not None,
            )
            source_items = (
                _project_items(connector, snapshot)
                if snapshot is not None and connected and binding is not None and binding.enabled
                else ()
            )
            sources.append(
                ConnectorFeedSource(
                    connector=connector,
                    label=definition.label,
                    health=health,
                    connected=connected,
                    enabled=enabled,
                    stale=stale,
                    item_count=len(source_items),
                    last_sync_at=binding.last_sync_at if binding is not None else None,
                    next_sync_at=binding.next_sync_at if binding is not None else None,
                    snapshot_fetched_at=snapshot.fetched_at if snapshot is not None else None,
                    fetch_strategy=definition.fetch_strategy,
                    coverage_past_days=definition.coverage_past_days,
                    coverage_future_days=definition.coverage_future_days,
                    raw_item_count=snapshot.raw_item_count if snapshot is not None else None,
                    normalized_item_count=(
                        snapshot.normalized_item_count if snapshot is not None else None
                    ),
                    normalization_health=_normalization_health(
                        error_code=binding.last_error_code if binding is not None else None,
                        snapshot=snapshot,
                    ),
                    last_error_code=binding.last_error_code if binding is not None else None,
                )
            )
            items.extend(source_items)
        items.sort(key=lambda item: (item.occurred_at, item.connector.value), reverse=True)
        return ConnectorFeed(
            workspace_id=workspace_id,
            generated_at=observed,
            sources=tuple(sources),
            items=tuple(items[:limit]),
        )


def _health(
    *,
    connected: bool,
    enabled: bool,
    stale: bool,
    error_code: str | None,
    has_snapshot: bool,
) -> ConnectorFeedHealth:
    if error_code in _OAUTH_RECONNECT_ERRORS:
        return ConnectorFeedHealth.REQUIRES_RECONNECT
    if not connected:
        return ConnectorFeedHealth.UNAVAILABLE
    if not enabled:
        return ConnectorFeedHealth.DISABLED
    if error_code is not None:
        return ConnectorFeedHealth.DEGRADED
    if not has_snapshot:
        return ConnectorFeedHealth.UNAVAILABLE
    if stale:
        return ConnectorFeedHealth.STALE
    return ConnectorFeedHealth.HEALTHY


def _normalization_health(
    *,
    error_code: str | None,
    snapshot: ConnectorSnapshot | None,
) -> ConnectorNormalizationHealth:
    if error_code == "invalid_response":
        return ConnectorNormalizationHealth.FAILED
    if (
        snapshot is None
        or snapshot.raw_item_count is None
        or snapshot.normalized_item_count is None
    ):
        return ConnectorNormalizationHealth.UNKNOWN
    if snapshot.raw_item_count > snapshot.normalized_item_count:
        return ConnectorNormalizationHealth.PARTIAL
    return ConnectorNormalizationHealth.HEALTHY


def _project_items(
    connector: ConnectorKind,
    snapshot: ConnectorSnapshot,
) -> tuple[ConnectorFeedItem, ...]:
    ordered = sorted(snapshot.items, key=lambda item: item.occurred_at, reverse=True)[:10]
    return tuple(
        ConnectorFeedItem(
            connector=connector,
            source_id=sanitize_untrusted_text(item.source_id)[:500],
            occurred_at=item.occurred_at,
            ends_at=item.ends_at,
            title=sanitize_untrusted_text(item.title)[:500],
            summary=sanitize_untrusted_text(item.summary)[:2_000],
            url=sanitize_untrusted_url(item.url) if item.url is not None else None,
        )
        for item in ordered
    )
