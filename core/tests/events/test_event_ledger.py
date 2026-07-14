from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from weatherflow.events import Actor, Event
from weatherflow.events.repository import DuplicateEventError, EventLedger, UnknownEventCursor
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


async def test_recent_stream_read_returns_newest_events_first(tmp_path: Path) -> None:
    ledger = await initialized_ledger(tmp_path / "weatherflow.db")
    now = datetime.now(UTC)
    events = [
        Event.new(
            type=f"rhythm.signal.{index}",
            actor=Actor.SYSTEM,
            stream_kind="workspace",
            stream_id="workspace-1",
            correlation_id="workspace-1",
            payload={"step": index},
        ).model_copy(update={"recorded_at": now + timedelta(seconds=index)})
        for index in range(3)
    ]
    for event in events:
        await ledger.append(event)

    assert await ledger.list_stream_recent("workspace", "workspace-1", limit=2) == [
        events[2],
        events[1],
    ]


async def test_list_stream_in_reads_uncommitted_event(tmp_path: Path) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    ledger = EventLedger(database)
    event = Event.new(
        type="run.created",
        actor=Actor.SYSTEM,
        stream_kind="run",
        stream_id="run-1",
        correlation_id="run-1",
        payload={},
    )

    async with database.transaction() as connection:
        await ledger.append_in(connection, event)
        events = await ledger.list_stream_in(connection, "run", "run-1")

    assert events == [event]


def test_ledger_has_no_update_or_delete_api(tmp_path: Path) -> None:
    ledger = EventLedger(Database(tmp_path / "weatherflow.db"))

    assert not hasattr(ledger, "update")
    assert not hasattr(ledger, "delete")


async def test_global_cursor_reads_committed_events_in_order(tmp_path: Path) -> None:
    ledger = await initialized_ledger(tmp_path / "weatherflow.db")
    events = [
        Event.new(
            type=f"event.{index}",
            actor=Actor.SYSTEM,
            stream_kind="test",
            stream_id=str(index),
            correlation_id=str(index),
            payload={},
        )
        for index in range(3)
    ]
    for event in events:
        await ledger.append(event)

    assert await ledger.list_after(None) == events
    assert await ledger.list_after(events[0].id) == events[1:]
    assert await ledger.list_after(events[0].id, limit=1) == [events[1]]

    with pytest.raises(UnknownEventCursor):
        await ledger.list_after("missing")
    with pytest.raises(ValueError):
        await ledger.list_after(None, limit=0)
