from pathlib import Path

import pytest

from weatherflow.events import Actor, Event, EventLedger
from weatherflow.storage import Database


async def test_transaction_rolls_back_event_on_error(tmp_path: Path) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    ledger = EventLedger(database)
    event = Event.new(
        type="test",
        actor=Actor.SYSTEM,
        stream_kind="test",
        stream_id="1",
        correlation_id="1",
        payload={},
    )

    with pytest.raises(RuntimeError):
        async with database.transaction() as connection:
            await ledger.append_in(connection, event)
            raise RuntimeError("rollback")

    assert await ledger.get(event.id) is None


async def test_transaction_commits_event(tmp_path: Path) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    ledger = EventLedger(database)
    event = Event.new(
        type="test",
        actor=Actor.SYSTEM,
        stream_kind="test",
        stream_id="1",
        correlation_id="1",
        payload={},
    )

    async with database.transaction() as connection:
        await ledger.append_in(connection, event)

    assert await ledger.get(event.id) == event
