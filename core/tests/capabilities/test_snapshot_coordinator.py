from pathlib import Path

import aiosqlite
import pytest

from weatherflow.capabilities import (
    CapabilityCatalog,
    CapabilityResolver,
    CapabilitySnapshotCoordinator,
    CapabilitySnapshotRepository,
    ToolEffect,
    ToolSpec,
)
from weatherflow.events import Event, EventLedger
from weatherflow.runs import RunCoordinator, RunRepository, RunStatus, RunVersionConflict
from weatherflow.storage import Database
from weatherflow.trust import SupervisedPolicy
from weatherflow.workspaces import Workspace


def tool(tool_id: str) -> ToolSpec:
    return ToolSpec(
        tool_id=tool_id,
        description=tool_id,
        input_schema={},
        output_schema={},
        effect=ToolEffect.OBSERVE,
        source="test",
        source_version="1",
    )


async def setup(tmp_path: Path, ledger_type=EventLedger):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    ledger = ledger_type(database)
    runs = RunRepository(database)
    run_coordinator = RunCoordinator(database, runs, ledger)
    run = await run_coordinator.create_run(
        client_request_id="request-1",
        user_intent="answer question",
        workspace_id="workspace-1",
    )
    snapshots = CapabilitySnapshotRepository(database)
    coordinator = CapabilitySnapshotCoordinator(
        database=database,
        snapshots=snapshots,
        runs=runs,
        ledger=ledger,
        resolver=CapabilityResolver(SupervisedPolicy()),
    )
    workspace = Workspace.new(
        name="WeatherFlow",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
    )
    return database, ledger, runs, snapshots, coordinator, workspace, run


async def test_freeze_persists_attaches_and_audits_atomically(tmp_path: Path) -> None:
    _, ledger, _, _, coordinator, workspace, run = await setup(tmp_path)
    catalog = CapabilityCatalog([tool("observe")])

    result = await coordinator.freeze_for_run(
        run_id=run.id,
        expected_run_version=0,
        catalog=catalog,
        catalog_revision="revision-1",
        workspace=workspace,
        requested_tool_ids={"observe"},
    )

    assert result.run.capability_snapshot_id == result.snapshot.id
    assert result.run.version == 1
    assert [item.tool_id for item in result.snapshot.tools] == ["observe"]
    events = await ledger.list_correlation(run.id)
    assert events[-1].type == "capability.snapshot_frozen"
    assert events[-1].payload["digest"] == result.snapshot.digest


async def test_retry_and_catalog_mutation_do_not_change_snapshot(tmp_path: Path) -> None:
    _, ledger, _, _, coordinator, workspace, run = await setup(tmp_path)
    catalog = CapabilityCatalog([tool("observe")])
    values = {
        "run_id": run.id,
        "expected_run_version": 0,
        "catalog": catalog,
        "catalog_revision": "revision-1",
        "workspace": workspace,
        "requested_tool_ids": {"observe"},
    }
    first = await coordinator.freeze_for_run(**values)
    before = await ledger.list_correlation(run.id)
    catalog.register(tool("new"))

    repeated = await coordinator.freeze_for_run(**values)

    assert repeated == first
    assert [item.tool_id for item in repeated.snapshot.tools] == ["observe"]
    assert await ledger.list_correlation(run.id) == before


async def test_stale_run_version_rolls_back_snapshot(tmp_path: Path) -> None:
    database, ledger, runs, snapshots, coordinator, workspace, run = await setup(tmp_path)
    run_coordinator = RunCoordinator(database, runs, ledger)
    await run_coordinator.transition(
        run_id=run.id,
        target=RunStatus.PLANNING,
        expected_version=0,
    )

    with pytest.raises(RunVersionConflict):
        await coordinator.freeze_for_run(
            run_id=run.id,
            expected_run_version=0,
            catalog=CapabilityCatalog([tool("observe")]),
            catalog_revision="revision-1",
            workspace=workspace,
            requested_tool_ids={"observe"},
        )

    assert await snapshots.get_by_run_id(run.id) is None


class FailingLedger(EventLedger):
    async def append_in(self, connection: aiosqlite.Connection, event: Event) -> None:
        if event.type == "capability.snapshot_frozen":
            raise RuntimeError("ledger failed")
        await super().append_in(connection, event)


async def test_audit_failure_rolls_back_snapshot_and_run_pointer(tmp_path: Path) -> None:
    _, _, runs, snapshots, coordinator, workspace, run = await setup(tmp_path, FailingLedger)

    with pytest.raises(RuntimeError, match="ledger failed"):
        await coordinator.freeze_for_run(
            run_id=run.id,
            expected_run_version=0,
            catalog=CapabilityCatalog([tool("observe")]),
            catalog_revision="revision-1",
            workspace=workspace,
            requested_tool_ids={"observe"},
        )

    stored = await runs.get(run.id)
    assert stored == run
    assert await snapshots.get_by_run_id(run.id) is None
