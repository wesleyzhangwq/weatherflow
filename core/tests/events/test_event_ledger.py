from pathlib import Path

import pytest

from weatherflow.events import Actor, Event
from weatherflow.events.repository import DuplicateEventError, EventLedger
from weatherflow.storage import Database


async def initialized_ledger(path: Path) -> EventLedger:
    database = Database(path)
    await database.initialize()
    return EventLedger(database)


async def test_append_and_get_preserve_typed_event(tmp_path: Path) -> None:
    ledger = await initialized_ledger(tmp_path / "weatherflow.db")
    event = Event.new(
        type="run.created",
        actor=Actor.USER,
        stream_kind="run",
        stream_id="run-1",
        correlation_id="run-1",
        payload={"intent": "prepare release"},
    )

    await ledger.append(event)

    assert await ledger.get(event.id) == event


async def test_append_rejects_duplicate_id_without_overwrite(tmp_path: Path) -> None:
    ledger = await initialized_ledger(tmp_path / "weatherflow.db")
    event = Event.new(
        type="run.created",
        actor=Actor.USER,
        stream_kind="run",
        stream_id="run-1",
        correlation_id="run-1",
        payload={"version": 1},
    )
    await ledger.append(event)

    with pytest.raises(DuplicateEventError):
        await ledger.append(event)

    stored = await ledger.get(event.id)
    assert stored is not None
    assert stored.payload == {"version": 1}


async def test_stream_and_correlation_reads_are_ordered(tmp_path: Path) -> None:
    ledger = await initialized_ledger(tmp_path / "weatherflow.db")
    first = Event.new(
        type="run.created",
        actor=Actor.USER,
        stream_kind="run",
        stream_id="run-1",
        correlation_id="run-1",
        payload={"step": 1},
    )
    second = Event.new(
        type="run.started",
        actor=Actor.SYSTEM,
        stream_kind="run",
        stream_id="run-1",
        correlation_id="run-1",
        causation_id=first.id,
        payload={"step": 2},
    )
    unrelated = Event.new(
        type="run.created",
        actor=Actor.USER,
        stream_kind="run",
        stream_id="run-2",
        correlation_id="run-2",
        payload={},
    )
    for event in (first, second, unrelated):
        await ledger.append(event)

    assert await ledger.list_stream("run", "run-1") == [first, second]
    assert await ledger.list_correlation("run-1") == [first, second]


def test_ledger_has_no_update_or_delete_api(tmp_path: Path) -> None:
    ledger = EventLedger(Database(tmp_path / "weatherflow.db"))

    assert not hasattr(ledger, "update")
    assert not hasattr(ledger, "delete")
