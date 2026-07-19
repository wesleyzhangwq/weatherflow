from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.capabilities.builtin import CalendarEvent
from weatherflow.config import Settings
from weatherflow.connectors import (
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
)
from weatherflow.connectors.calendar import ComposioCalendarAdapter
from weatherflow.extensions import CredentialRef, MappingCredentialStore
from weatherflow.runtime import (
    FinalTurn,
    ToolCallTurn,
    ToolExecutionContext,
    ToolExecutionResult,
)


class RecordingExecutor:
    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self.outputs = outputs
        self.calls: list[tuple[str, dict[str, Any], ToolExecutionContext]] = []

    async def execute(self, tool, arguments, context):
        self.calls.append((tool.tool_id, arguments, context))
        return ToolExecutionResult(output=self.outputs.pop(0))


class CalendarGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute_tool(self, **call):
        self.calls.append(call)
        return {
            "items": [
                {
                    "id": "event-1",
                    "summary": "Planning block",
                    "start": {"dateTime": "2026-07-17T09:00:00+08:00"},
                    "end": {"dateTime": "2026-07-17T09:30:00+08:00"},
                }
            ]
        }


class CalendarModel:
    def __init__(self) -> None:
        self.turns = [
            ToolCallTurn(
                tool_id="calendar.list_events",
                arguments={
                    "start": "2026-07-17T00:00:00+08:00",
                    "end": "2026-07-18T00:00:00+08:00",
                },
            ),
            FinalTurn(content="Calendar read complete."),
        ]

    async def complete(self, request):
        return self.turns.pop(0)


async def test_calendar_adapter_maps_bounded_list_through_canonical_composio_tool() -> None:
    executor = RecordingExecutor(
        [
            {
                "ok": True,
                "data": {
                    "items": [
                        {
                            "id": "event-1",
                            "summary": "Planning block",
                            "start": {"dateTime": "2026-07-17T09:00:00+08:00"},
                            "end": {"dateTime": "2026-07-17T09:30:00+08:00"},
                            "htmlLink": "https://calendar.example/event-1",
                        }
                    ]
                },
            }
        ]
    )
    adapter = ComposioCalendarAdapter(executor=executor)
    context = ToolExecutionContext(run_id="run-1", workspace_id="workspace-1")

    events = await adapter.list_events(
        start="2026-07-17T00:00:00+08:00",
        end="2026-07-18T00:00:00+08:00",
        limit=999,
        context=context,
    )

    assert events == (
        CalendarEvent(
            event_id="event-1",
            title="Planning block",
            start="2026-07-17T09:00:00+08:00",
            end="2026-07-17T09:30:00+08:00",
            url="https://calendar.example/event-1",
        ),
    )
    assert executor.calls == [
        (
            "composio.google_calendar.list_events",
            {
                "timeMin": "2026-07-17T00:00:00+08:00",
                "timeMax": "2026-07-18T00:00:00+08:00",
                "maxResults": 50,
            },
            context,
        )
    ]


async def test_calendar_adapter_maps_approved_create_without_exposing_credentials() -> None:
    executor = RecordingExecutor(
        [
            {
                "ok": True,
                "data": {
                    "id": "event-created",
                    "summary": "Focus block",
                    "start": {"dateTime": "2026-07-17T10:00:00+08:00"},
                    "end": {"dateTime": "2026-07-17T11:30:00+08:00"},
                },
            }
        ]
    )
    adapter = ComposioCalendarAdapter(executor=executor)
    context = ToolExecutionContext(
        run_id="run-1",
        workspace_id="workspace-1",
        action_id="action-1",
        idempotency_key="run-1:action-1",
    )

    event = await adapter.create_event(
        title="Focus block",
        start="2026-07-17T10:00:00+08:00",
        end="2026-07-17T11:30:00+08:00",
        idempotency_key="run-1:action-1",
        context=context,
    )

    assert event.event_id == "event-created"
    assert executor.calls == [
        (
            "composio.google_calendar.create_event",
            {
                "summary": "Focus block",
                "start_datetime": "2026-07-17T10:00:00+08:00",
                "timezone": "Asia/Shanghai",
                "event_duration_minutes": 90,
            },
            context,
        )
    ]


async def test_calendar_adapter_rejects_create_without_matching_approved_action() -> None:
    executor = RecordingExecutor([])
    adapter = ComposioCalendarAdapter(executor=executor)

    with pytest.raises(PermissionError, match="approved Action"):
        await adapter.create_event(
            title="Focus block",
            start="2026-07-17T10:00:00+08:00",
            end="2026-07-17T11:00:00+08:00",
            idempotency_key="expected",
            context=ToolExecutionContext(run_id="run-1", workspace_id="workspace-1"),
        )

    assert executor.calls == []


async def test_legacy_calendar_tool_uses_the_frozen_composio_run_route(
    tmp_path: Path,
) -> None:
    gateway = CalendarGateway()
    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path / "data"),
        model=CalendarModel(),
        connector_gateway=gateway,  # type: ignore[arg-type]
        credential_store=MappingCredentialStore(
            {"provider_continuations.encryption_key_v1": "a" * 64}
        ),  # type: ignore[arg-type]
    )
    project = tmp_path / "project"
    project.mkdir()
    workspace = await container.authorize_workspace(name="Project", path=project)
    now = datetime.now(UTC)
    account = ConnectorAccount.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GOOGLE_CALENDAR,
        external_account_id="ca_calendar",
        credential_ref=CredentialRef(provider="composio", name="project_api_key"),
        now=now,
    ).activate(now=now)
    binding = ConnectorBinding.new(
        workspace_id=workspace.id,
        connector=ConnectorKind.GOOGLE_CALENDAR,
        account_id=account.id,
        now=now,
    )
    await container.connector_repository.save_account(account)
    await container.connector_repository.save_binding(binding)

    run, outcome = await container.submit_run(
        user_intent="Read today's Calendar",
        workspace_id=workspace.id,
    )

    snapshot = await container.snapshots.get_by_run_id(run.id)
    assert outcome is not None and outcome.result_summary == "Calendar read complete."
    assert snapshot is not None
    assert "calendar.list_events" in {tool.tool_id for tool in snapshot.tools}
    assert gateway.calls[0]["action"] == "GOOGLECALENDAR_EVENTS_LIST"
    assert gateway.calls[0]["connected_account_id"] == "ca_calendar"
    assert gateway.calls[0]["arguments"]["calendarId"] == "primary"
