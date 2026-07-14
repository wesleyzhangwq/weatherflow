from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from weatherflow.connectors import (
    CONNECTOR_DEFINITIONS,
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
    ConnectorRepository,
    ConnectorSyncService,
)
from weatherflow.events import EventLedger
from weatherflow.extensions import CredentialRef
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository


class FakeReadGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def execute_read_action(
        self,
        *,
        action: str,
        connected_account_id: str,
        arguments: dict[str, Any],
    ) -> Any:
        self.calls.append((action, connected_account_id, arguments))
        if action == "GITHUB_GET_THE_AUTHENTICATED_USER":
            return {"login": "wesz"}
        if action == "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS":
            return {
                "items": [
                    {
                        "id": 123,
                        "title": "Review release",
                        "body": "Check the release candidate",
                        "updated_at": "2026-07-13T03:00:00Z",
                        "html_url": "https://github.com/wesz/weatherflow/issues/123",
                    }
                ]
            }
        if action == "GMAIL_FETCH_EMAILS":
            return {
                "messages": [
                    {
                        "id": "mail-1",
                        "subject": "Deployment",
                        "snippet": "The deployment completed.",
                        "date": "2026-07-13T04:00:00Z",
                    }
                ]
            }
        if action == "GOOGLECALENDAR_EVENTS_LIST":
            return {
                "items": [
                    {
                        "id": "event-1",
                        "summary": "Release review",
                        "description": "Review the release candidate",
                        "start": {"dateTime": "2026-07-13T10:00:00+08:00"},
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
        assert len(snapshot.items) == 1
        assert snapshot.items[0].source_id
        assert snapshot.items[0].occurred_at.tzinfo is not None
        assert await repository.get_snapshot(workspace.id, connector) == snapshot
        binding = await repository.get_binding(workspace.id, connector)
        assert binding is not None and binding.last_sync_at == now
        assert all(
            call[0]
            in {
                "GITHUB_GET_THE_AUTHENTICATED_USER",
                "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS",
                "GMAIL_FETCH_EMAILS",
                "GOOGLECALENDAR_EVENTS_LIST",
            }
            for call in gateway.calls
        )
        if connector is ConnectorKind.GOOGLE_CALENDAR:
            assert gateway.calls == [
                (
                    "GOOGLECALENDAR_EVENTS_LIST",
                    "ca_google_calendar",
                    {
                        "calendarId": "primary",
                        "timeMin": now.isoformat(),
                        "timeMax": (now + timedelta(days=14)).isoformat(),
                        "singleEvents": True,
                        "timeZone": "Asia/Shanghai",
                        "maxResults": 50,
                    },
                )
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
        *, action: str, connected_account_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id
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


async def test_connector_snapshot_redacts_tokens_and_url_credentials(tmp_path: Path) -> None:
    workspace, _repository, gateway, service, _now = await setup(tmp_path, ConnectorKind.GMAIL)
    token = "ghp_" + "sensitivevalue12345"
    url_secret = "calendar-secret-value"

    async def sensitive_response(
        *, action: str, connected_account_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id, arguments
        return {
            "messages": [
                {
                    "id": "mail-with-secret",
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


async def test_due_sync_isolates_unexpected_gateway_or_normalization_failure(
    tmp_path: Path,
) -> None:
    workspace, repository, gateway, service, now = await setup(tmp_path, ConnectorKind.GMAIL)
    upstream_secret = "upstream response body must not be durable"

    async def fail_once(
        *, action: str, connected_account_id: str, arguments: dict[str, Any]
    ) -> Any:
        del action, connected_account_id, arguments
        raise ValueError(upstream_secret)

    gateway.execute_read_action = fail_once  # type: ignore[method-assign]

    assert await service.sync_due() == []
    failed_binding = await repository.get_binding(workspace.id, ConnectorKind.GMAIL)
    assert failed_binding is not None
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


@pytest.mark.parametrize("failure", [RuntimeError("transport failed"), ValueError("bad data")])
async def test_due_sync_never_propagates_one_binding_failure(
    tmp_path: Path, failure: Exception
) -> None:
    _workspace, _repository, gateway, service, _now = await setup(tmp_path, ConnectorKind.GMAIL)

    async def reject(*, action: str, connected_account_id: str, arguments: dict[str, Any]) -> Any:
        del action, connected_account_id, arguments
        raise failure

    gateway.execute_read_action = reject  # type: ignore[method-assign]

    assert await service.sync_due() == []
