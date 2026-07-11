from datetime import UTC, datetime, timedelta
from pathlib import Path

from weatherflow.artifacts import ArtifactRepository, ArtifactStore
from weatherflow.capabilities import ToolEffect
from weatherflow.capabilities.builtin import (
    CalendarEvent,
    PersonalOperationsExecutor,
    personal_tool_specs,
)
from weatherflow.events import EventLedger
from weatherflow.rhythm import (
    CurrentRhythm,
    DimensionEstimate,
    DimensionName,
    Freshness,
    HumanStateSnapshot,
    RhythmPolicy,
    Trend,
    WeatherPresentation,
    WeatherScene,
    WorkMode,
)
from weatherflow.runs import Run, RunRepository
from weatherflow.runtime import ToolExecutionContext
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository


class FakeCalendarProvider:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.listed: list[tuple[str, str, int]] = []

    async def list_events(self, *, start: str, end: str, limit: int):
        self.listed.append((start, end, limit))
        return (
            CalendarEvent(
                event_id="meeting-1",
                title="WeatherFlow release review",
                start="2026-07-13T10:00:00+08:00",
                end="2026-07-13T10:30:00+08:00",
                url="https://calendar.example/meeting-1",
            ),
        )

    async def create_event(self, **kwargs):
        self.created.append(kwargs["title"])
        raise AssertionError("proposal tools must never mutate Calendar")


class FakeRhythm:
    def __init__(self, current: CurrentRhythm) -> None:
        self.value = current

    async def current(self, workspace_id: str) -> CurrentRhythm:
        assert workspace_id == self.value.snapshot.workspace_id
        return self.value


def overloaded_rhythm(workspace_id: str) -> CurrentRhythm:
    now = datetime.now(UTC)
    dimensions = {
        name: DimensionEstimate(
            value=(
                0.9 if name in {DimensionName.COGNITIVE_LOAD, DimensionName.RECOVERY_NEED} else 0.4
            ),
            confidence=0.9,
            trend=Trend.RISING,
            supporting_event_ids=("rhythm-source-1",),
            contradicting_event_ids=(),
            freshness=Freshness.FRESH,
        )
        for name in DimensionName
    }
    snapshot = HumanStateSnapshot.new(
        workspace_id=workspace_id,
        observed_at=now,
        window_start=now - timedelta(hours=1),
        window_end=now,
        dimensions=dimensions,
        summary="High load and recovery need",
        supporting_event_ids=("rhythm-source-1",),
        contradicting_event_ids=(),
        valid_until=now + timedelta(hours=1),
    )
    return CurrentRhythm(
        snapshot=snapshot,
        policy=RhythmPolicy(
            interaction_budget="minimal",
            response_density="compact",
            delegation_bias="favor",
            scope_pressure="reduce",
            work_mode=WorkMode.SINGLE_THREAD,
            reason_refs=("rhythm-source-1",),
            valid_until=snapshot.valid_until,
        ),
        weather=WeatherPresentation(
            scene=WeatherScene.STORM,
            intensity=0.9,
            transition="building",
            snapshot_id=snapshot.id,
            valid_until=snapshot.valid_until,
        ),
    )


async def setup_executor(tmp_path: Path):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = Workspace.new(
        name="Personal",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
        granted_scopes={"workspace:write", "calendar:read"},
        installed_packs={"personal_operations"},
    )
    workspaces = WorkspaceRepository(database)
    await workspaces.create(workspace)
    run = Run.new(
        client_request_id="personal-request",
        user_intent="Plan a low-burden day",
        workspace_id=workspace.id,
    )
    async with database.transaction() as connection:
        await RunRepository(database).create_in(connection, run)
    ledger = EventLedger(database)
    artifacts = ArtifactRepository(database)
    store = ArtifactStore(database=database, repository=artifacts, ledger=ledger)
    provider = FakeCalendarProvider()
    executor = PersonalOperationsExecutor(
        workspaces=workspaces,
        artifacts=store,
        rhythm=FakeRhythm(overloaded_rhythm(workspace.id)),
        calendar=provider,
    )
    context = ToolExecutionContext(run_id=run.id, workspace_id=workspace.id)
    return executor, context, artifacts, provider, workspace


def spec(tool_id: str):
    return next(item for item in personal_tool_specs() if item.tool_id == tool_id)


async def test_overloaded_day_plan_reduces_density_and_adds_recovery(tmp_path: Path) -> None:
    executor, context, artifacts, _, workspace = await setup_executor(tmp_path)

    result = await executor.execute(
        spec("personal.plan_day"),
        {
            "date": "2026-07-13",
            "tasks": ["Ship release", "Fix docs", "Triage bugs", "Refactor", "Inbox"],
        },
        context,
    )

    assert result.output["selected_tasks"] == ["Ship release", "Fix docs", "Triage bugs"]
    assert result.output["deferred_tasks"] == ["Refactor", "Inbox"]
    assert result.output["recovery_buffer_minutes"] == 30
    manifest = (await artifacts.list_run(context.run_id))[0]
    content = (Path(workspace.artifact_root) / manifest.relative_path).read_text()
    assert "Single-thread plan" in content
    assert "Recovery buffer: 30 minutes" in content
    assert manifest.validation["rhythm_snapshot_id"]


async def test_meeting_preparation_preserves_calendar_and_rhythm_provenance(
    tmp_path: Path,
) -> None:
    executor, context, artifacts, provider, workspace = await setup_executor(tmp_path)

    result = await executor.execute(
        spec("personal.prepare_meeting"),
        {
            "start": "2026-07-13T00:00:00+08:00",
            "end": "2026-07-14T00:00:00+08:00",
            "event_id": "meeting-1",
            "objectives": ["Confirm release blockers", "Assign owners"],
        },
        context,
    )

    assert result.output["source_event_id"] == "meeting-1"
    assert result.output["rhythm_reason_refs"] == ["rhythm-source-1"]
    manifest = (await artifacts.list_run(context.run_id))[0]
    content = (Path(workspace.artifact_root) / manifest.relative_path).read_text()
    assert "WeatherFlow release review" in content
    assert "Confirm release blockers" in content
    assert provider.created == []


async def test_schedule_proposal_never_mutates_calendar(tmp_path: Path) -> None:
    executor, context, artifacts, provider, workspace = await setup_executor(tmp_path)

    result = await executor.execute(
        spec("personal.propose_schedule"),
        {
            "start": "2026-07-13T00:00:00+08:00",
            "end": "2026-07-14T00:00:00+08:00",
            "tasks": ["Ship release", "Write follow-up"],
        },
        context,
    )

    assert result.output["calendar_mutated"] is False
    assert result.output["requires_calendar_action"] is True
    assert provider.created == []
    manifest = (await artifacts.list_run(context.run_id))[0]
    content = (Path(workspace.artifact_root) / manifest.relative_path).read_text()
    assert "Proposal only" in content
    assert "calendar.create_event" in content


def test_personal_tools_are_local_artifacts_or_calendar_reads() -> None:
    effects = {tool.tool_id: tool.effect for tool in personal_tool_specs()}

    assert effects == {
        "personal.plan_day": ToolEffect.WORKSPACE_WRITE,
        "personal.prepare_meeting": ToolEffect.NETWORK_READ,
        "personal.propose_schedule": ToolEffect.NETWORK_READ,
    }
    assert spec("personal.plan_day").required_scopes == frozenset({"workspace:write"})
    assert spec("personal.propose_schedule").required_scopes == frozenset(
        {"workspace:write", "calendar:read"}
    )
