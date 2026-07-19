import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from weatherflow.connectors import (
    CONNECTOR_DEFINITIONS,
    ComposioErrorCode,
    ComposioGatewayError,
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
    ConnectorRepository,
    ConnectorSnapshot,
    ConnectorSyncService,
    SourceItem,
)
from weatherflow.events import EventLedger
from weatherflow.extensions import CredentialRef, CredentialUnavailableError
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository


class FakeReadGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict[str, Any]]] = []

    async def execute_read_action(
        self,
        *,
        action: str,
        connected_account_id: str,
        user_id: str,
        arguments: dict[str, Any],
    ) -> Any:
        self.calls.append((action, connected_account_id, user_id, arguments))
        if action == "GITHUB_GET_THE_AUTHENTICATED_USER":
            return {"login": "wesz"}
        if action == "GITHUB_LIST_NOTIFICATIONS":
            return {
                "notifications": [
                    {
                        "id": "notification-123",
                        "subject": {"title": "Review release"},
                        "reason": "review_requested",
                        "updated_at": "2026-07-13T03:00:00Z",
                        "url": "https://api.github.com/notifications/threads/123",
                    }
                ]
            }
        if action == "GITHUB_SEARCH_COMMITS":
            return {
                "items": [
                    {
                        "sha": "commit-456",
                        "html_url": "https://github.com/wesz/weatherflow/commit/commit-456",
                        "commit": {
                            "message": "Release prep",
                            "author": {"date": "2026-07-12T03:00:00Z"},
                        },
                    }
                ]
            }
        if action == "GMAIL_FETCH_EMAILS":
            return {
                "messages": [
                    {
                        "messageId": "mail-1",
                        "threadId": "thread-1",
                        "subject": "Deployment",
                        "preview": {"body": "The deployment completed."},
                        "messageText": "full body that must never be stored",
                        "messageTimestamp": "2026-07-13T04:00:00Z",
                        "display_url": "https://mail.google.com/mail/u/0/#inbox/mail-1",
                    }
                ]
            }
        if action == "GOOGLECALENDAR_EVENTS_LIST_ALL_CALENDARS":
            return {
                "items": [
                    {
                        "id": "event-1",
                        "summary": "Release review",
                        "description": "Review the release candidate",
                        "start": {"dateTime": "2026-07-13T10:00:00+08:00"},
                        "end": {"dateTime": "2026-07-13T11:00:00+08:00"},
                        "htmlLink": "https://calendar.google.com/event?eid=event-1",
                    }
                ]
            }
        raise AssertionError(action)


async def setup(tmp_path: Path, connector: ConnectorKind):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = Workspace.new(
        name="Sync",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await WorkspaceRepository(database).create(workspace)
    repository = ConnectorRepository(database)
    now = datetime(2026, 7, 13, 5, tzinfo=UTC)
    account = ConnectorAccount.new(
        workspace_id=workspace.id,
        connector=connector,
        external_account_id=f"ca_{connector.value}",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now,
    ).activate(now=now)
    binding = ConnectorBinding.new(
        workspace_id=workspace.id,
        connector=connector,
        account_id=account.id,
        now=now,
    ).model_copy(update={"next_sync_at": now - timedelta(seconds=1)})
    await repository.save_account(account)
    await repository.save_binding(binding)
    gateway = FakeReadGateway()
    service = ConnectorSyncService(
        repository=repository,
        ledger=EventLedger(database),
        gateway=gateway,
        user_id="wf-installation",
        now=lambda: now,
        timezone="Asia/Shanghai",
    )
    return workspace, repository, gateway, service, now


async def test_fixed_read_fetchers_create_bounded_source_linked_snapshots(
    tmp_path: Path,
) -> None:
    for connector, definition in CONNECTOR_DEFINITIONS.items():
        if not definition.auto_fetch_supported:
            continue
        workspace, repository, gateway, service, now = await setup(
            tmp_path / connector.value, connector
        )

        snapshot = await service.sync(workspace.id, connector)

        assert snapshot.workspace_id == workspace.id
        assert snapshot.connector is connector
        assert snapshot.fetched_at == now
        assert len(snapshot.items) == (2 if connector is ConnectorKind.GITHUB else 1)
        assert snapshot.raw_item_count == len(snapshot.items)
        assert snapshot.normalized_item_count == len(snapshot.items)
        assert snapshot.items[0].source_id
        assert snapshot.items[0].occurred_at.tzinfo is not None
        assert await repository.get_snapshot(workspace.id, connector) == snapshot
        binding = await repository.get_binding(workspace.id, connector)
        assert binding is not None and binding.last_sync_at == now
        assert all(
            call[0]
            in {
                "GITHUB_GET_THE_AUTHENTICATED_USER",
                "GITHUB_LIST_NOTIFICATIONS",
                "GITHUB_SEARCH_COMMITS",
                "GMAIL_FETCH_EMAILS",
                "GOOGLECALENDAR_EVENTS_LIST_ALL_CALENDARS",
            }
            for call in gateway.calls
        )
        if connector is ConnectorKind.GOOGLE_CALENDAR:
            assert snapshot.items[0].ends_at == datetime.fromisoformat("2026-07-13T11:00:00+08:00")
            assert gateway.calls == [
                (
                    "GOOGLECALENDAR_EVENTS_LIST_ALL_CALENDARS",
                    "ca_google_calendar",
                    "wf-installation",
                    {
                        "time_min": "2026-07-06T00:00:00+08:00",
                        "time_max": "2026-07-27T00:00:00+08:00",
                        "single_events": True,
                        "show_deleted": False,
                        "max_results_per_calendar": 20,
                    },
                )
            ]


async def test_github_fetches_unread_notifications_and_recent_authenticated_activity(
    tmp_path: Path,
) -> None:
    workspace, _repository, gateway, service, _now = await setup(tmp_path, ConnectorKind.GITHUB)

    snapshot = await service.sync(workspace.id, ConnectorKind.GITHUB)

    assert {item.source_id for item in snapshot.items} == {
        "notification-123",
        "commit-456",
    }
    assert gateway.calls == [
        (
            "GITHUB_GET_THE_AUTHENTICATED_USER",
            "ca_github",
            "wf-installation",
            {},
        ),
        (
            "GITHUB_LIST_NOTIFICATIONS",
            "ca_github",
            "wf-installation",
            {
                "all": False,
                "participating": False,
                "since": "2026-07-06T05:00:00+00:00",
                "per_page": 50,
                "page": 1,
            },
        ),
        (
            "GITHUB_SEARCH_COMMITS",
            "ca_github",
            "wf-installation",
            {
                "q": "author:wesz committer-date:>=2026-07-06",
                "sort": "committer-date",
                "order": "desc",
                "per_page": 50,
                "page": 1,
            },
        ),
    ]


async def test_catalog_only_connector_cannot_enter_automatic_fetch_path(tmp_path: Path) -> None:
    workspace, _repository, _gateway, service, _now = await setup(tmp_path, ConnectorKind.SLACK)

    with pytest.raises(LookupError, match="automatic fetch unsupported"):
        await service.sync(workspace.id, ConnectorKind.SLACK)


async def test_due_sync_skips_disabled_binding(tmp_path: Path) -> None:
    workspace, repository, gateway, service, now = await setup(tmp_path, ConnectorKind.GMAIL)
    binding = await repository.get_binding(workspace.id, ConnectorKind.GMAIL)
    assert binding is not None
    await repository.save_binding(
        binding.model_copy(
            update={
                "auto_fetch_enabled": False,
                "version": binding.version + 1,
                "updated_at": now,
            }
        )
    )

    synced = await service.sync_due()

    assert synced == []
    assert gateway.calls == []


async def test_gmail_snapshot_never_falls_back_to_full_message_body(tmp_path: Path) -> None:
    workspace, _repository, gateway, service, _now = await setup(tmp_path, ConnectorKind.GMAIL)
    private_body = "full private email body that must not be persisted"

    async def body_only_response(
        *, action: str, connected_account_id: str, user_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id, user_id
        assert arguments["include_payload"] is False
        return {
            "messages": [
                {
                    "id": "mail-without-snippet",
                    "subject": "Private message",
                    "body": private_body,
                    "date": "2026-07-13T04:00:00Z",
                }
            ]
        }

    gateway.execute_read_action = body_only_response  # type: ignore[method-assign]

    snapshot = await service.sync(workspace.id, ConnectorKind.GMAIL)

    assert snapshot.items[0].summary == ""
    assert private_body not in snapshot.model_dump_json()


async def test_gmail_normalizes_live_camel_case_metadata_without_persisting_body(
    tmp_path: Path,
) -> None:
    workspace, _repository, gateway, service, _now = await setup(tmp_path, ConnectorKind.GMAIL)

    snapshot = await service.sync(workspace.id, ConnectorKind.GMAIL)

    assert len(snapshot.items) == 1
    item = snapshot.items[0]
    assert item.source_id == "mail-1"
    assert item.occurred_at == datetime(2026, 7, 13, 4, tzinfo=UTC)
    assert item.summary == "The deployment completed."
    assert item.url == "https://mail.google.com/mail/u/0/"
    assert "full body that must never be stored" not in snapshot.model_dump_json()
    assert gateway.calls[0][3] == {
        "query": "is:unread newer_than:30d -in:spam -in:trash",
        "max_results": 50,
        "include_payload": False,
    }


async def test_nonempty_unparseable_response_degrades_without_replacing_snapshot(
    tmp_path: Path,
) -> None:
    workspace, repository, gateway, service, now = await setup(tmp_path, ConnectorKind.GMAIL)
    previous = ConnectorSnapshot(
        workspace_id=workspace.id,
        connector=ConnectorKind.GMAIL,
        fetched_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=1),
        raw_item_count=1,
        normalized_item_count=1,
        items=(
            SourceItem(
                source_id="previous-mail",
                occurred_at=now - timedelta(days=1),
                title="Previous safe metadata",
                summary="Previous bounded preview",
            ),
        ),
    )
    await repository.replace_snapshot(previous)

    async def incompatible_response(
        *, action: str, connected_account_id: str, user_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id, user_id, arguments
        return {"messages": [{"unexpected": "shape"}]}

    gateway.execute_read_action = incompatible_response  # type: ignore[method-assign]

    with pytest.raises(ComposioGatewayError) as raised:
        await service.sync(workspace.id, ConnectorKind.GMAIL)

    assert raised.value.code is ComposioErrorCode.UPSTREAM
    assert await repository.get_snapshot(workspace.id, ConnectorKind.GMAIL) == previous
    binding = await repository.get_binding(workspace.id, ConnectorKind.GMAIL)
    assert binding is not None
    assert binding.last_error_code == "invalid_response"


@pytest.mark.parametrize(
    "drifted_payload",
    (
        {"mailRecords": [{"messageId": "new-shape"}]},
        {},
        {"messages": [None]},
    ),
)
async def test_invalid_envelope_cannot_be_misreported_as_true_empty(
    tmp_path: Path,
    drifted_payload: dict[str, Any],
) -> None:
    workspace, repository, gateway, service, now = await setup(tmp_path, ConnectorKind.GMAIL)
    previous = ConnectorSnapshot(
        workspace_id=workspace.id,
        connector=ConnectorKind.GMAIL,
        fetched_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=1),
        raw_item_count=1,
        normalized_item_count=1,
        items=(
            SourceItem(
                source_id="previous-mail",
                occurred_at=now - timedelta(days=1),
                title="Previous safe metadata",
                summary="Previous bounded preview",
            ),
        ),
    )
    await repository.replace_snapshot(previous)

    async def drifted_envelope(
        *, action: str, connected_account_id: str, user_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id, user_id, arguments
        return drifted_payload

    gateway.execute_read_action = drifted_envelope  # type: ignore[method-assign]

    with pytest.raises(ComposioGatewayError):
        await service.sync(workspace.id, ConnectorKind.GMAIL)

    assert await repository.get_snapshot(workspace.id, ConnectorKind.GMAIL) == previous
    binding = await repository.get_binding(workspace.id, ConnectorKind.GMAIL)
    assert binding is not None and binding.last_error_code == "invalid_response"


async def test_invalid_required_gmail_timestamp_is_partial_normalization_loss(
    tmp_path: Path,
) -> None:
    workspace, _repository, gateway, service, _now = await setup(tmp_path, ConnectorKind.GMAIL)

    async def mixed_timestamp_response(
        *, action: str, connected_account_id: str, user_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id, user_id, arguments
        return {
            "messages": [
                {
                    "messageId": "mail-valid",
                    "subject": "Valid timestamp",
                    "messageTimestamp": "2026-07-13T04:00:00Z",
                },
                {
                    "messageId": "mail-invalid",
                    "subject": "Invalid timestamp",
                    "messageTimestamp": "not-a-timestamp",
                },
                None,
            ]
        }

    gateway.execute_read_action = mixed_timestamp_response  # type: ignore[method-assign]

    snapshot = await service.sync(workspace.id, ConnectorKind.GMAIL)

    assert snapshot.raw_item_count == 3
    assert snapshot.normalized_item_count == 1
    assert [item.source_id for item in snapshot.items] == ["mail-valid"]


async def test_missing_required_calendar_start_cannot_fall_back_to_sync_time(
    tmp_path: Path,
) -> None:
    workspace, _repository, gateway, service, _now = await setup(
        tmp_path, ConnectorKind.GOOGLE_CALENDAR
    )

    async def missing_start_response(
        *, action: str, connected_account_id: str, user_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id, user_id, arguments
        return {"items": [{"id": "event-without-start", "summary": "No start"}]}

    gateway.execute_read_action = missing_start_response  # type: ignore[method-assign]

    with pytest.raises(ComposioGatewayError) as raised:
        await service.sync(workspace.id, ConnectorKind.GOOGLE_CALENDAR)

    assert raised.value.code is ComposioErrorCode.UPSTREAM


async def test_calendar_end_before_start_cannot_replace_previous_snapshot(
    tmp_path: Path,
) -> None:
    workspace, repository, gateway, service, now = await setup(
        tmp_path, ConnectorKind.GOOGLE_CALENDAR
    )
    previous = ConnectorSnapshot(
        workspace_id=workspace.id,
        connector=ConnectorKind.GOOGLE_CALENDAR,
        fetched_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=1),
        raw_item_count=1,
        normalized_item_count=1,
        items=(
            SourceItem(
                source_id="previous-event",
                occurred_at=now - timedelta(days=1),
                ends_at=now - timedelta(days=1) + timedelta(hours=1),
                title="Previous valid event",
                summary="Previous bounded metadata",
            ),
        ),
    )
    await repository.replace_snapshot(previous)

    async def reversed_event_response(
        *, action: str, connected_account_id: str, user_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id, user_id, arguments
        return {
            "items": [
                {
                    "id": "reversed-event",
                    "summary": "Invalid range",
                    "start": {"dateTime": "2026-07-13T11:00:00+08:00"},
                    "end": {"dateTime": "2026-07-13T10:00:00+08:00"},
                }
            ]
        }

    gateway.execute_read_action = reversed_event_response  # type: ignore[method-assign]

    with pytest.raises(ComposioGatewayError) as raised:
        await service.sync(workspace.id, ConnectorKind.GOOGLE_CALENDAR)

    assert raised.value.code is ComposioErrorCode.UPSTREAM
    assert await repository.get_snapshot(workspace.id, ConnectorKind.GOOGLE_CALENDAR) == previous
    binding = await repository.get_binding(workspace.id, ConnectorKind.GOOGLE_CALENDAR)
    assert binding is not None and binding.last_error_code == "invalid_response"


async def test_duplicate_provider_ids_are_deduped_without_normalization_loss(
    tmp_path: Path,
) -> None:
    workspace, _repository, gateway, service, _now = await setup(tmp_path, ConnectorKind.GMAIL)

    async def duplicate_response(
        *, action: str, connected_account_id: str, user_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id, user_id, arguments
        row = {
            "messageId": "mail-duplicate",
            "subject": "Duplicate provider row",
            "preview": {"body": "Bounded preview"},
            "messageTimestamp": "2026-07-13T04:00:00Z",
        }
        return {"messages": [row, dict(row)]}

    gateway.execute_read_action = duplicate_response  # type: ignore[method-assign]

    snapshot = await service.sync(workspace.id, ConnectorKind.GMAIL)

    assert snapshot.raw_item_count == 2
    assert snapshot.normalized_item_count == 2
    assert len(snapshot.items) == 1


@pytest.mark.parametrize("mutation", ["disable", "delete"])
async def test_inflight_sync_cannot_resurrect_changed_or_deleted_binding(
    tmp_path: Path,
    mutation: str,
) -> None:
    workspace, repository, gateway, service, now = await setup(tmp_path, ConnectorKind.GMAIL)
    previous = ConnectorSnapshot(
        workspace_id=workspace.id,
        connector=ConnectorKind.GMAIL,
        fetched_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=1),
        raw_item_count=1,
        normalized_item_count=1,
        items=(
            SourceItem(
                source_id="previous-mail",
                occurred_at=now - timedelta(days=1),
                title="Previous safe metadata",
                summary="Previous bounded preview",
            ),
        ),
    )
    await repository.replace_snapshot(previous)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_response(
        *, action: str, connected_account_id: str, user_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id, user_id, arguments
        started.set()
        await release.wait()
        return {
            "messages": [
                {
                    "messageId": "new-mail",
                    "subject": "New safe metadata",
                    "messageTimestamp": "2026-07-13T04:30:00Z",
                }
            ]
        }

    gateway.execute_read_action = blocked_response  # type: ignore[method-assign]
    task = asyncio.create_task(service.sync(workspace.id, ConnectorKind.GMAIL))
    await started.wait()
    binding = await repository.get_binding(workspace.id, ConnectorKind.GMAIL)
    assert binding is not None
    if mutation == "disable":
        await repository.save_binding(
            binding.model_copy(
                update={
                    "auto_fetch_enabled": False,
                    "version": binding.version + 1,
                    "updated_at": now,
                }
            )
        )
    else:
        await repository.delete_snapshot(workspace.id, ConnectorKind.GMAIL)
        await repository.delete_binding(workspace.id, ConnectorKind.GMAIL)
    release.set()

    with pytest.raises(LookupError, match="changed during sync"):
        await task

    current = await repository.get_binding(workspace.id, ConnectorKind.GMAIL)
    snapshot = await repository.get_snapshot(workspace.id, ConnectorKind.GMAIL)
    if mutation == "disable":
        assert current is not None and current.auto_fetch_enabled is False
        assert snapshot == previous
    else:
        assert current is None
        assert snapshot is None
    events = await service.ledger.list_stream("connector", ConnectorKind.GMAIL.value)
    assert events[-1].type == "connector.sync_discarded"
    assert events[-1].payload["reason"] == "binding_changed"


async def test_connector_snapshot_redacts_tokens_and_url_credentials(tmp_path: Path) -> None:
    workspace, _repository, gateway, service, _now = await setup(tmp_path, ConnectorKind.GMAIL)
    token = "ghp_" + "sensitivevalue12345"
    url_secret = "calendar-secret-value"

    async def sensitive_response(
        *, action: str, connected_account_id: str, user_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id, user_id, arguments
        return {
            "messages": [
                {
                    "id": token,
                    "subject": f"Deploy with {token}",
                    "snippet": f"Authorization: Bearer {token}",
                    "url": f"https://mail.example/messages/1?access_token={url_secret}",
                    "date": "2026-07-13T04:00:00Z",
                }
            ]
        }

    gateway.execute_read_action = sensitive_response  # type: ignore[method-assign]

    snapshot = await service.sync(workspace.id, ConnectorKind.GMAIL)
    serialized = snapshot.model_dump_json()

    assert token not in serialized
    assert url_secret not in serialized
    assert "[redacted]" in serialized
    assert snapshot.items[0].url == "https://mail.example/messages/1"
    assert snapshot.items[0].source_id == "[redacted]"
    events = await service.ledger.list_stream("connector", ConnectorKind.GMAIL.value)
    synced_event = events[-1]
    assert "source_ids" not in synced_event.payload
    digests = synced_event.payload["source_id_digests"]
    assert isinstance(digests, list)
    assert len(digests) == 1 and len(digests[0]) == 64
    assert token not in synced_event.model_dump_json()


async def test_due_sync_isolates_unexpected_gateway_or_normalization_failure(
    tmp_path: Path,
) -> None:
    workspace, repository, gateway, service, now = await setup(tmp_path, ConnectorKind.GMAIL)
    binding = await repository.get_binding(workspace.id, ConnectorKind.GMAIL)
    assert binding is not None
    previous_success = now - timedelta(hours=1)
    await repository.save_binding(
        binding.after_sync(now=previous_success).model_copy(
            update={"next_sync_at": now - timedelta(seconds=1)}
        )
    )
    upstream_secret = "upstream response body must not be durable"

    async def fail_once(
        *, action: str, connected_account_id: str, user_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id, user_id, arguments
        raise ValueError(upstream_secret)

    gateway.execute_read_action = fail_once  # type: ignore[method-assign]

    assert await service.sync_due() == []
    failed_binding = await repository.get_binding(workspace.id, ConnectorKind.GMAIL)
    assert failed_binding is not None
    assert failed_binding.last_sync_at == previous_success
    assert failed_binding.last_error_code == "invalid_response"
    events = await service.ledger.list_stream("connector", ConnectorKind.GMAIL.value)
    assert events[-1].payload["error_code"] == "invalid_response"
    assert upstream_secret not in str(events[-1].payload)

    gateway.execute_read_action = FakeReadGateway().execute_read_action  # type: ignore[method-assign]
    await repository.save_binding(
        failed_binding.model_copy(
            update={
                "next_sync_at": now - timedelta(seconds=1),
                "version": failed_binding.version + 1,
                "updated_at": now,
            }
        )
    )

    recovered = await service.sync_due()

    assert len(recovered) == 1
    assert recovered[0].connector is ConnectorKind.GMAIL


async def test_temporarily_unavailable_credential_keeps_due_and_recovers_after_unlock(
    tmp_path: Path,
) -> None:
    workspace, repository, gateway, service, now = await setup(tmp_path, ConnectorKind.GMAIL)
    binding = await repository.get_binding(workspace.id, ConnectorKind.GMAIL)
    assert binding is not None and binding.next_sync_at <= now
    previous = ConnectorSnapshot(
        workspace_id=workspace.id,
        connector=ConnectorKind.GMAIL,
        fetched_at=now - timedelta(days=1),
        expires_at=now - timedelta(hours=1),
        raw_item_count=1,
        normalized_item_count=1,
        items=(
            SourceItem(
                source_id="previous-mail",
                occurred_at=now - timedelta(days=1),
                title="Previous safe metadata",
                summary="Previous bounded preview",
            ),
        ),
    )
    await repository.replace_snapshot(previous)
    original_fetch = gateway.execute_read_action
    keychain_locked = True

    async def fetch_after_unlock(
        *, action: str, connected_account_id: str, user_id: str, arguments: dict[str, Any]
    ) -> Any:
        if keychain_locked:
            raise CredentialUnavailableError("composio.project_api_key")
        return await original_fetch(
            action=action,
            connected_account_id=connected_account_id,
            user_id=user_id,
            arguments=arguments,
        )

    gateway.execute_read_action = fetch_after_unlock  # type: ignore[method-assign]

    assert await service.sync_due() == []
    assert await repository.get_binding(workspace.id, ConnectorKind.GMAIL) == binding
    assert await repository.get_snapshot(workspace.id, ConnectorKind.GMAIL) == previous
    events = await service.ledger.list_stream("connector", ConnectorKind.GMAIL.value)
    assert not any(event.type == "connector.sync_failed" for event in events)

    keychain_locked = False
    recovered = await service.sync_due()

    assert len(recovered) == 1
    refreshed = await repository.get_binding(workspace.id, ConnectorKind.GMAIL)
    assert refreshed is not None
    assert refreshed.last_sync_at == now
    assert refreshed.next_sync_at == now + timedelta(days=1)


async def test_concurrent_due_sync_rechecks_schedule_inside_broker_lock(
    tmp_path: Path,
) -> None:
    workspace, repository, gateway, service, _now = await setup(tmp_path, ConnectorKind.GMAIL)
    fetch_started = asyncio.Event()
    release_fetch = asyncio.Event()
    listed_twice = asyncio.Event()
    fetch_count = 0
    list_count = 0
    original_list_due_bindings = repository.list_due_bindings

    async def tracked_list_due_bindings(observed: datetime) -> list[ConnectorBinding]:
        nonlocal list_count
        bindings = await original_list_due_bindings(observed)
        list_count += 1
        if list_count == 2:
            listed_twice.set()
        return bindings

    async def blocked_fetch(
        *, action: str, connected_account_id: str, user_id: str, arguments: dict[str, Any]
    ) -> Any:
        nonlocal fetch_count
        del action, connected_account_id, user_id, arguments
        fetch_count += 1
        fetch_started.set()
        await release_fetch.wait()
        return {
            "messages": [
                {
                    "messageId": "mail-once",
                    "subject": "Only fetched once",
                    "messageTimestamp": "2026-07-13T04:30:00Z",
                }
            ]
        }

    repository.list_due_bindings = tracked_list_due_bindings  # type: ignore[method-assign]
    gateway.execute_read_action = blocked_fetch  # type: ignore[method-assign]

    first = asyncio.create_task(service.sync_due())
    await fetch_started.wait()
    second = asyncio.create_task(service.sync_due())
    await listed_twice.wait()
    release_fetch.set()

    first_result, second_result = await asyncio.gather(first, second)

    assert len(first_result) == 1
    assert second_result == []
    assert fetch_count == 1
    events = await service.ledger.list_stream("connector", ConnectorKind.GMAIL.value)
    assert [event.type for event in events].count("connector.synced") == 1


@pytest.mark.parametrize("failure", [RuntimeError("transport failed"), ValueError("bad data")])
async def test_due_sync_never_propagates_one_binding_failure(
    tmp_path: Path, failure: Exception
) -> None:
    _workspace, _repository, gateway, service, _now = await setup(tmp_path, ConnectorKind.GMAIL)

    async def reject(
        *, action: str, connected_account_id: str, user_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id, user_id, arguments
        raise failure

    gateway.execute_read_action = reject  # type: ignore[method-assign]

    assert await service.sync_due() == []
