from pathlib import Path

import aiosqlite
import pytest

from weatherflow.events import Event, EventLedger
from weatherflow.runs import (
    InvalidTransitionError,
    RunCoordinator,
    RunRepository,
    RunStatus,
)
from weatherflow.storage import Database


async def make_coordinator(
    tmp_path: Path,
) -> tuple[Database, RunRepository, EventLedger, RunCoordinator]:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    repository = RunRepository(database)
    ledger = EventLedger(database)
    return database, repository, ledger, RunCoordinator(database, repository, ledger)


async def test_create_run_is_idempotent_and_audited(tmp_path: Path) -> None:
    _, _, ledger, coordinator = await make_coordinator(tmp_path)

    first = await coordinator.create_run(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    repeated = await coordinator.create_run(
        client_request_id="request-1",
        user_intent="ignored duplicate intent",
        workspace_id="workspace-1",
    )

    events = await ledger.list_stream("run", first.id)
    assert first.status is RunStatus.QUEUED
    assert repeated == first
    assert [event.type for event in events] == ["run.created"]
    assert events[0].payload == {
        "client_request_id": "request-1",
        "workspace_id": "workspace-1",
        "status": "queued",
    }


async def test_transition_is_versioned_and_audited(tmp_path: Path) -> None:
    _, _, ledger, coordinator = await make_coordinator(tmp_path)
    run = await coordinator.create_run(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )

    updated = await coordinator.transition(
        run_id=run.id,
        target=RunStatus.PLANNING,
        expected_version=0,
    )

    events = await ledger.list_stream("run", run.id)
    assert updated.status is RunStatus.PLANNING
    assert updated.version == 1
    assert [event.type for event in events] == ["run.created", "run.status_changed"]
    assert events[-1].causation_id == events[0].id
    assert events[-1].payload == {"from": "queued", "to": "planning", "version": 1}


async def test_invalid_transition_changes_nothing(tmp_path: Path) -> None:
    _, repository, ledger, coordinator = await make_coordinator(tmp_path)
    run = await coordinator.create_run(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    planning = await coordinator.transition(
        run_id=run.id,
        target=RunStatus.PLANNING,
        expected_version=0,
    )
    before = await ledger.list_stream("run", run.id)

    with pytest.raises(InvalidTransitionError):
        await coordinator.transition(
            run_id=run.id,
            target=RunStatus.SUCCEEDED,
            expected_version=planning.version,
        )

    stored = await repository.get(run.id)
    assert stored == planning
    assert await ledger.list_stream("run", run.id) == before


class FailingLedger(EventLedger):
    async def append_in(self, connection: aiosqlite.Connection, event: Event) -> None:
        raise RuntimeError("ledger failed")


async def test_event_failure_rolls_back_transition(tmp_path: Path) -> None:
    database, repository, ledger, coordinator = await make_coordinator(tmp_path)
    run = await coordinator.create_run(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    failing = RunCoordinator(database, repository, FailingLedger(database))

    with pytest.raises(RuntimeError, match="ledger failed"):
        await failing.transition(
            run_id=run.id,
            target=RunStatus.PLANNING,
            expected_version=0,
        )

    stored = await repository.get(run.id)
    assert stored == run
    assert [event.type for event in await ledger.list_stream("run", run.id)] == ["run.created"]
