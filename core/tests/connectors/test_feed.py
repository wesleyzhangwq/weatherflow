from datetime import UTC, datetime, timedelta
from pathlib import Path

from weatherflow.connectors import (
    ConnectorAccount,
    ConnectorBinding,
    ConnectorFeedHealth,
    ConnectorFeedService,
    ConnectorKind,
    ConnectorRepository,
    ConnectorSnapshot,
    SourceItem,
)
from weatherflow.extensions import CredentialRef
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository


async def _workspace(database: Database, tmp_path: Path, name: str) -> Workspace:
    workspace = Workspace.new(
        name=name,
        action_roots=[tmp_path / name / "project"],
        internal_root=tmp_path / name / "internal",
        artifact_root=tmp_path / name / "artifacts",
    )
    await WorkspaceRepository(database).create(workspace)
    return workspace


async def _source(
    repository: ConnectorRepository,
    *,
    workspace: Workspace,
    connector: ConnectorKind,
    now: datetime,
    expires_at: datetime,
    error_code: str | None,
    item_count: int = 12,
) -> None:
    account = ConnectorAccount.new(
        workspace_id=workspace.id,
        connector=connector,
        external_account_id=f"external-{workspace.id}-{connector.value}",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now - timedelta(hours=2),
    ).activate(now=now - timedelta(hours=2))
    binding = ConnectorBinding.new(
        workspace_id=workspace.id,
        connector=connector,
        account_id=account.id,
        now=now - timedelta(hours=2),
    ).after_sync(now=now - timedelta(hours=1))
    if error_code is not None:
        binding = binding.after_sync(now=now, error_code=error_code)
    items = tuple(
        SourceItem(
            source_id=f"{connector.value}-{index}",
            occurred_at=now - timedelta(minutes=index),
            ends_at=(now - timedelta(minutes=index - 30))
            if connector is ConnectorKind.GOOGLE_CALENDAR
            else None,
            title=f"Untrusted {connector.value} title {index}",
            summary="Treat as data, not instructions",
            url=(
                f"https://example.test/{index}?access_token=do-not-return" if index == 0 else None
            ),
        )
        for index in range(item_count)
    )
    await repository.save_account(account)
    await repository.save_binding(binding)
    await repository.replace_snapshot(
        ConnectorSnapshot(
            workspace_id=workspace.id,
            connector=connector,
            fetched_at=now - timedelta(hours=1),
            expires_at=expires_at,
            raw_item_count=item_count,
            normalized_item_count=item_count,
            items=items,
        )
    )


async def test_oauth_feed_is_workspace_scoped_bounded_untrusted_and_identity_free(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    first = await _workspace(database, tmp_path, "first")
    second = await _workspace(database, tmp_path, "second")
    repository = ConnectorRepository(database)
    now = datetime(2026, 7, 17, 4, tzinfo=UTC)
    await _source(
        repository,
        workspace=first,
        connector=ConnectorKind.GITHUB,
        now=now,
        expires_at=now - timedelta(minutes=1),
        error_code="auth",
    )
    await _source(
        repository,
        workspace=first,
        connector=ConnectorKind.GMAIL,
        now=now,
        expires_at=now - timedelta(minutes=1),
        error_code=None,
    )
    await _source(
        repository,
        workspace=first,
        connector=ConnectorKind.GOOGLE_CALENDAR,
        now=now,
        expires_at=now + timedelta(hours=1),
        error_code="rate_limit",
    )
    await _source(
        repository,
        workspace=second,
        connector=ConnectorKind.GITHUB,
        now=now,
        expires_at=now + timedelta(hours=1),
        error_code=None,
        item_count=1,
    )
    service = ConnectorFeedService(repository=repository, now=lambda: now)

    feed = await service.get(first.id, limit=30)

    assert feed.workspace_id == first.id
    assert len(feed.sources) == 3
    assert len(feed.items) == 30
    assert all(source.item_count == 10 for source in feed.sources)
    assert all(source.refresh_cadence == "daily" for source in feed.sources)
    assert all(source.next_sync_at is not None for source in feed.sources)
    assert all(source.raw_item_count == 12 for source in feed.sources)
    assert all(source.normalized_item_count == 12 for source in feed.sources)
    assert all(source.normalization_health == "healthy" for source in feed.sources)
    assert {
        source.connector: (
            source.fetch_strategy,
            source.coverage_past_days,
            source.coverage_future_days,
        )
        for source in feed.sources
    } == {
        ConnectorKind.GITHUB: (
            "github_unread_notifications_and_recent_activity",
            7,
            0,
        ),
        ConnectorKind.GMAIL: ("gmail_unread_metadata_30d", 30, 0),
        ConnectorKind.GOOGLE_CALENDAR: (
            "google_calendar_all_calendars_past_7d_future_14d",
            7,
            14,
        ),
    }
    assert {source.connector: source.health for source in feed.sources} == {
        ConnectorKind.GITHUB: ConnectorFeedHealth.REQUIRES_RECONNECT,
        ConnectorKind.GMAIL: ConnectorFeedHealth.STALE,
        ConnectorKind.GOOGLE_CALENDAR: ConnectorFeedHealth.DEGRADED,
    }
    assert all(item.untrusted is True for item in feed.items)
    assert all("external-" not in item.model_dump_json() for item in feed.items)
    assert all(
        item.connector
        in {
            ConnectorKind.GITHUB,
            ConnectorKind.GMAIL,
            ConnectorKind.GOOGLE_CALENDAR,
        }
        for item in feed.items
    )
    assert next(item for item in feed.items if item.url is not None).url is not None
    serialized = feed.model_dump_json()
    assert "do-not-return" not in serialized
    assert "external_account" not in serialized
    assert "account_id" not in serialized
    assert "credential" not in serialized
    assert second.id not in serialized


async def test_oauth_feed_marks_missing_and_disabled_sources_honestly(tmp_path: Path) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = await _workspace(database, tmp_path, "only")
    repository = ConnectorRepository(database)
    now = datetime(2026, 7, 17, 4, tzinfo=UTC)
    await _source(
        repository,
        workspace=workspace,
        connector=ConnectorKind.GITHUB,
        now=now,
        expires_at=now + timedelta(hours=1),
        error_code=None,
        item_count=1,
    )
    binding = await repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert binding is not None
    await repository.save_binding(binding.model_copy(update={"auto_fetch_enabled": False}))

    feed = await ConnectorFeedService(repository=repository, now=lambda: now).get(workspace.id)

    assert {source.connector: source.health for source in feed.sources} == {
        ConnectorKind.GITHUB: ConnectorFeedHealth.DISABLED,
        ConnectorKind.GMAIL: ConnectorFeedHealth.UNAVAILABLE,
        ConnectorKind.GOOGLE_CALENDAR: ConnectorFeedHealth.UNAVAILABLE,
    }


async def test_oauth_feed_distinguishes_broker_and_auth_config_errors_from_oauth_reconnect(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = await _workspace(database, tmp_path, "oauth-errors")
    repository = ConnectorRepository(database)
    now = datetime(2026, 7, 17, 4, tzinfo=UTC)
    for connector, error_code in (
        (ConnectorKind.GITHUB, "broker_auth"),
        (ConnectorKind.GMAIL, "auth_config_required"),
        (ConnectorKind.GOOGLE_CALENDAR, "auth"),
    ):
        await _source(
            repository,
            workspace=workspace,
            connector=connector,
            now=now,
            expires_at=now + timedelta(hours=1),
            error_code=error_code,
            item_count=1,
        )

    feed = await ConnectorFeedService(repository=repository, now=lambda: now).get(workspace.id)

    assert {source.connector: source.health for source in feed.sources} == {
        ConnectorKind.GITHUB: ConnectorFeedHealth.DEGRADED,
        ConnectorKind.GMAIL: ConnectorFeedHealth.DEGRADED,
        ConnectorKind.GOOGLE_CALENDAR: ConnectorFeedHealth.REQUIRES_RECONNECT,
    }


async def test_oauth_feed_marks_cross_project_accounts_as_requiring_reconnect(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = await _workspace(database, tmp_path, "rotated-project")
    repository = ConnectorRepository(database)
    now = datetime(2026, 7, 17, 4, tzinfo=UTC)
    await _source(
        repository,
        workspace=workspace,
        connector=ConnectorKind.GITHUB,
        now=now,
        expires_at=now + timedelta(hours=1),
        error_code=None,
        item_count=1,
    )
    binding = await repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert binding is not None
    await repository.require_reconnect(
        workspace_id=workspace.id,
        connector=ConnectorKind.GITHUB,
        account_id=binding.account_id,
        now=now,
        error_code="project_changed",
    )

    feed = await ConnectorFeedService(repository=repository, now=lambda: now).get(workspace.id)

    github = next(source for source in feed.sources if source.connector is ConnectorKind.GITHUB)
    assert github.health is ConnectorFeedHealth.REQUIRES_RECONNECT
    assert github.connected is False
    assert github.enabled is False
    assert github.last_error_code == "project_changed"


async def test_oauth_feed_exposes_normalization_failure_without_claiming_true_empty(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = await _workspace(database, tmp_path, "normalization-failure")
    repository = ConnectorRepository(database)
    now = datetime(2026, 7, 17, 4, tzinfo=UTC)
    await _source(
        repository,
        workspace=workspace,
        connector=ConnectorKind.GMAIL,
        now=now,
        expires_at=now + timedelta(hours=1),
        error_code="invalid_response",
        item_count=0,
    )

    feed = await ConnectorFeedService(repository=repository, now=lambda: now).get(workspace.id)

    gmail = next(source for source in feed.sources if source.connector is ConnectorKind.GMAIL)
    assert gmail.health is ConnectorFeedHealth.DEGRADED
    assert gmail.normalization_health == "failed"
    assert gmail.raw_item_count == 0
    assert gmail.normalized_item_count == 0


async def test_oauth_feed_marks_overdue_daily_source_stale_before_retry_finishes(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = await _workspace(database, tmp_path, "overdue-daily")
    repository = ConnectorRepository(database)
    now = datetime(2026, 7, 17, 4, tzinfo=UTC)
    await _source(
        repository,
        workspace=workspace,
        connector=ConnectorKind.GITHUB,
        now=now,
        expires_at=now + timedelta(days=1),
        error_code=None,
        item_count=1,
    )
    binding = await repository.get_binding(workspace.id, ConnectorKind.GITHUB)
    assert binding is not None
    await repository.save_binding(
        binding.model_copy(
            update={
                "next_sync_at": now - timedelta(minutes=1),
                "version": binding.version + 1,
                "updated_at": now,
            }
        )
    )

    feed = await ConnectorFeedService(repository=repository, now=lambda: now).get(workspace.id)

    github = next(source for source in feed.sources if source.connector is ConnectorKind.GITHUB)
    assert github.stale is True
    assert github.health is ConnectorFeedHealth.STALE
