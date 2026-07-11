from pathlib import Path

import pytest

from weatherflow.capabilities import IdempotencyKind, ToolEffect
from weatherflow.capabilities.builtin import (
    CalendarEvent,
    CalendarExecutor,
    GitHubExecutor,
    GitHubRelease,
    calendar_tool_specs,
    github_tool_specs,
)
from weatherflow.events import EventLedger
from weatherflow.runs import RunCoordinator, RunRepository, RunStatus
from weatherflow.runtime import ActionExecutionCoordinator, ToolExecutionContext
from weatherflow.storage import Database
from weatherflow.trust import (
    Action,
    ActionRepository,
    ActionStatus,
    ApprovalPolicyError,
    SupervisedPolicy,
)
from weatherflow.workspaces import Workspace


class FakeCalendarProvider:
    def __init__(self) -> None:
        self.created: list[str] = []

    async def list_events(self, *, start: str, end: str, limit: int):
        return (
            CalendarEvent(
                event_id="event-1",
                title="Release focus block",
                start=start,
                end=end,
            ),
        )

    async def create_event(
        self,
        *,
        title: str,
        start: str,
        end: str,
        idempotency_key: str,
    ) -> CalendarEvent:
        self.created.append(idempotency_key)
        return CalendarEvent(
            event_id="event-created",
            title=title,
            start=start,
            end=end,
        )


class FakeGitHubProvider:
    def __init__(self) -> None:
        self.created: list[str] = []

    async def inspect_release(self, *, repository: str, tag: str):
        return None

    async def create_release(
        self,
        *,
        repository: str,
        tag: str,
        name: str,
        body: str,
        idempotency_key: str,
    ) -> GitHubRelease:
        self.created.append(idempotency_key)
        return GitHubRelease(
            repository=repository,
            tag=tag,
            status="published",
            url="https://github.example/releases/v3",
        )


def spec(specs, tool_id: str):
    return next(item for item in specs() if item.tool_id == tool_id)


async def test_read_operations_are_bounded_network_reads() -> None:
    calendar = FakeCalendarProvider()
    github = FakeGitHubProvider()
    context = ToolExecutionContext(run_id="run-1", workspace_id="workspace-1")

    events = await CalendarExecutor(calendar).execute(
        spec(calendar_tool_specs, "calendar.list_events"),
        {
            "start": "2026-07-12T00:00:00Z",
            "end": "2026-07-13T00:00:00Z",
            "limit": 999,
        },
        context,
    )
    release = await GitHubExecutor(github).execute(
        spec(github_tool_specs, "github.inspect_release"),
        {"repository": "tinyhumansai/openhuman", "tag": "v3.0.0"},
        context,
    )

    assert events.output["events"][0]["event_id"] == "event-1"
    assert events.output["limit"] == 50
    assert release.output == {"release": None}
    assert spec(calendar_tool_specs, "calendar.list_events").effect is ToolEffect.NETWORK_READ
    assert spec(github_tool_specs, "github.inspect_release").effect is ToolEffect.NETWORK_READ


@pytest.mark.parametrize(
    ("tool", "executor_factory", "provider_factory", "arguments"),
    [
        (
            lambda: spec(calendar_tool_specs, "calendar.create_event"),
            CalendarExecutor,
            FakeCalendarProvider,
            {
                "title": "Recovery block",
                "start": "2026-07-13T09:00:00+08:00",
                "end": "2026-07-13T10:00:00+08:00",
            },
        ),
        (
            lambda: spec(github_tool_specs, "github.create_release"),
            GitHubExecutor,
            FakeGitHubProvider,
            {
                "repository": "wesz/weatherflow",
                "tag": "v3.0.0",
                "name": "WeatherFlow v3",
                "body": "Validated release",
            },
        ),
    ],
)
async def test_external_mutation_waits_for_approval_and_executes_exactly_once(
    tmp_path: Path,
    tool,
    executor_factory,
    provider_factory,
    arguments,
) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    ledger = EventLedger(database)
    runs = RunRepository(database)
    run_coordinator = RunCoordinator(database, runs, ledger)
    run = await run_coordinator.create_run(
        client_request_id="request-1",
        user_intent="ship",
        workspace_id="workspace-1",
    )
    run = await run_coordinator.transition(
        run_id=run.id,
        target=RunStatus.PLANNING,
        expected_version=run.version,
    )
    await run_coordinator.transition(
        run_id=run.id,
        target=RunStatus.RUNNING,
        expected_version=run.version,
    )
    selected = tool()
    assert selected.effect is ToolEffect.EXTERNAL_WRITE
    assert selected.idempotency is IdempotencyKind.KEY
    action = Action.new(
        run_id=run.id,
        tool_id=selected.tool_id,
        arguments=arguments,
        effect=selected.effect,
        idempotency_key=f"{run.id}:approved-action",
        preview=arguments,
    )
    actions = ActionRepository(database)
    async with database.transaction() as connection:
        await actions.create_in(connection, action)
    workspace = Workspace.new(
        name="Operations",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
        granted_scopes=selected.required_scopes,
    )
    coordinator = ActionExecutionCoordinator(
        database=database,
        actions=actions,
        runs=runs,
        run_coordinator=run_coordinator,
        ledger=ledger,
        policy=SupervisedPolicy(),
    )
    provider = provider_factory()
    executor = executor_factory(provider)

    with pytest.raises(ApprovalPolicyError):
        await coordinator.execute(
            action_id=action.id,
            tool=selected,
            workspace=workspace,
            executor=executor,
        )
    assert provider.created == []

    async with database.transaction() as connection:
        approved = await actions.transition_in(
            connection,
            action.id,
            ActionStatus.APPROVED,
            action.version,
        )
    completed = await coordinator.execute(
        action_id=approved.id,
        tool=selected,
        workspace=workspace,
        executor=executor,
    )
    assert completed.result is not None
    assert provider.created == [action.idempotency_key]

    with pytest.raises(ApprovalPolicyError):
        await coordinator.execute(
            action_id=action.id,
            tool=selected,
            workspace=workspace,
            executor=executor,
        )
    assert provider.created == [action.idempotency_key]
