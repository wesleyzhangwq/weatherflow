# WeatherFlow v3 P1a Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the minimal local SQLite foundation and append-only Event Ledger that later Run, Approval, Rhythm, Memory, and Artifact domains can share.

**Architecture:** A single `Database` adapter owns SQLite connections, WAL mode, foreign-key enforcement, and numbered migrations. The Event domain owns a typed immutable envelope and `EventLedger`; no other domain writes the `events` table directly. P1a creates no operational Run tables and no generic ORM layer.

**Tech Stack:** Python 3.12, aiosqlite, python-ulid, Pydantic v2, pytest-asyncio, uv, Ruff.

---

## Files after P1a

```text
core/src/weatherflow/
├── events/
│   ├── __init__.py
│   ├── models.py
│   └── repository.py
└── storage/
    ├── __init__.py
    ├── database.py
    └── migrations.py

core/tests/
├── events/test_event_ledger.py
└── storage/test_database.py
```

## Locked contracts

- SQLite uses WAL mode and foreign keys on every connection.
- Migrations are numbered and applied once inside a transaction.
- `events` is append-only through the public Python API.
- Event payload is typed as JSON-compatible data; secrets are represented only
  by references before reaching this layer.
- Event IDs are ULIDs; timestamps are timezone-aware UTC strings.
- Duplicate IDs fail explicitly and never overwrite.
- Stream and correlation reads are ordered by `(recorded_at, id)`.
- Retention deletion is deferred; P1a exposes no delete/update event method.

---

### Task 1: Add storage dependencies and a failing database contract

**Files:**
- Modify: `core/pyproject.toml`
- Create: `core/tests/storage/test_database.py`

- [ ] **Step 1: Add runtime dependencies**

Add these entries to `core/pyproject.toml` runtime dependencies:

```toml
    "aiosqlite>=0.20,<1.0",
    "python-ulid>=2.7,<3.0",
```

- [ ] **Step 2: Create the storage test directory**

Run:

```bash
mkdir -p core/tests/storage
```

- [ ] **Step 3: Write the failing database initialization test**

Create `core/tests/storage/test_database.py`:

```python
from pathlib import Path

import aiosqlite

from weatherflow.storage.database import Database


async def test_initialize_creates_versioned_wal_database(tmp_path: Path) -> None:
    path = tmp_path / "weatherflow.db"
    database = Database(path)

    await database.initialize()

    assert path.is_file()
    async with aiosqlite.connect(path) as connection:
        journal_mode = await (await connection.execute("PRAGMA journal_mode")).fetchone()
        migration = await (
            await connection.execute("SELECT version FROM schema_migrations")
        ).fetchone()
        event_table = await (
            await connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'events'"
            )
        ).fetchone()

    assert journal_mode == ("wal",)
    assert migration == (1,)
    assert event_table == ("events",)


async def test_connection_enables_foreign_keys(tmp_path: Path) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()

    async with database.connect() as connection:
        foreign_keys = await (await connection.execute("PRAGMA foreign_keys")).fetchone()

    assert tuple(foreign_keys) == (1,)


async def test_initialize_is_idempotent(tmp_path: Path) -> None:
    database = Database(tmp_path / "weatherflow.db")

    await database.initialize()
    await database.initialize()

    async with database.connect() as connection:
        count = await (
            await connection.execute("SELECT COUNT(*) FROM schema_migrations")
        ).fetchone()

    assert tuple(count) == (1,)
```

- [ ] **Step 4: Run the test and verify RED**

Run:

```bash
uv lock
uv sync --all-packages --all-extras --locked
uv run --package weatherflow-core --extra dev pytest core/tests/storage/test_database.py -q
```

Expected: collection fails because `weatherflow.storage.database` does not
exist. Dependency import must succeed.

---

### Task 2: Implement Database and migration 1

**Files:**
- Create: `core/src/weatherflow/storage/__init__.py`
- Create: `core/src/weatherflow/storage/migrations.py`
- Create: `core/src/weatherflow/storage/database.py`

- [ ] **Step 1: Define migration 1**

Create `core/src/weatherflow/storage/migrations.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    sql: str


MIGRATIONS = (
    Migration(
        version=1,
        sql="""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            stream_kind TEXT NOT NULL,
            stream_id TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            causation_id TEXT,
            payload TEXT NOT NULL,
            sensitivity TEXT NOT NULL,
            retention_class TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_events_stream
            ON events(stream_kind, stream_id, recorded_at, id);
        CREATE INDEX IF NOT EXISTS idx_events_correlation
            ON events(correlation_id, recorded_at, id);
        """,
    ),
)
```

- [ ] **Step 2: Implement the Database adapter**

Create `core/src/weatherflow/storage/database.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from weatherflow.storage.migrations import MIGRATIONS


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await aiosqlite.connect(self.path)
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            await connection.close()

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as connection:
            await connection.execute("PRAGMA journal_mode = WAL")
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            rows = await (
                await connection.execute("SELECT version FROM schema_migrations")
            ).fetchall()
            applied = {int(row["version"]) for row in rows}
            await connection.commit()
            for migration in MIGRATIONS:
                if migration.version in applied:
                    continue
                await connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    f"{migration.sql}\n"
                    "INSERT INTO schema_migrations(version) "
                    f"VALUES ({migration.version});\n"
                    "COMMIT;"
                )
```

Create `core/src/weatherflow/storage/__init__.py`:

```python
"""Local persistence adapters."""

from weatherflow.storage.database import Database

__all__ = ["Database"]
```

- [ ] **Step 3: Run the database tests and verify GREEN**

Run:

```bash
uv run --package weatherflow-core --extra dev pytest core/tests/storage/test_database.py -q
```

Expected: `3 passed` with no warnings.

- [ ] **Step 4: Run storage lint and formatting**

Run:

```bash
uv run --package weatherflow-core --extra dev ruff check \
  core/src/weatherflow/storage core/tests/storage
uv run --package weatherflow-core --extra dev ruff format --check \
  core/src/weatherflow/storage core/tests/storage
```

Expected: both commands exit 0.

- [ ] **Step 5: Commit the storage foundation**

Run:

```bash
git add core/pyproject.toml uv.lock core/src/weatherflow/storage core/tests/storage
git diff --cached --check
git commit -m "feat: add WeatherFlow SQLite foundation"
```

---

### Task 3: Define the immutable Event envelope with TDD

**Files:**
- Create: `core/tests/events/test_event_models.py`
- Create: `core/src/weatherflow/events/__init__.py`
- Create: `core/src/weatherflow/events/models.py`

- [ ] **Step 1: Write failing Event model tests**

Create `core/tests/events/test_event_models.py`:

```python
from datetime import UTC

import pytest
from pydantic import ValidationError

from weatherflow.events.models import Actor, Event, RetentionClass, Sensitivity


def test_event_new_generates_ulid_and_utc_timestamp() -> None:
    event = Event.new(
        type="run.created",
        actor=Actor.USER,
        stream_kind="run",
        stream_id="run-1",
        correlation_id="run-1",
        payload={"intent": "prepare release"},
    )

    assert len(event.id) == 26
    assert event.recorded_at.tzinfo is UTC
    assert event.sensitivity is Sensitivity.NORMAL
    assert event.retention_class is RetentionClass.AUDIT


def test_event_is_immutable() -> None:
    event = Event.new(
        type="run.created",
        actor=Actor.SYSTEM,
        stream_kind="run",
        stream_id="run-1",
        correlation_id="run-1",
        payload={},
    )

    with pytest.raises(ValidationError):
        event.type = "run.changed"
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
mkdir -p core/tests/events
uv run --package weatherflow-core --extra dev pytest \
  core/tests/events/test_event_models.py -q
```

Expected: collection fails because `weatherflow.events.models` does not exist.

- [ ] **Step 3: Implement the immutable Event model**

Create `core/src/weatherflow/events/models.py`:

```python
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID


class Actor(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class Sensitivity(StrEnum):
    NORMAL = "normal"
    PRIVATE = "private"
    SECRET_REF = "secret_ref"


class RetentionClass(StrEnum):
    AUDIT = "audit"
    SIGNAL_RAW = "signal_raw"
    SIGNAL_AGGREGATE = "signal_aggregate"


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    type: str = Field(min_length=1)
    recorded_at: datetime
    actor: Actor
    stream_kind: str = Field(min_length=1)
    stream_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    causation_id: str | None = None
    payload: dict[str, Any]
    sensitivity: Sensitivity = Sensitivity.NORMAL
    retention_class: RetentionClass = RetentionClass.AUDIT

    @classmethod
    def new(
        cls,
        *,
        type: str,
        actor: Actor,
        stream_kind: str,
        stream_id: str,
        correlation_id: str,
        payload: dict[str, Any],
        causation_id: str | None = None,
        sensitivity: Sensitivity = Sensitivity.NORMAL,
        retention_class: RetentionClass = RetentionClass.AUDIT,
    ) -> "Event":
        return cls(
            id=str(ULID()),
            type=type,
            recorded_at=datetime.now(UTC),
            actor=actor,
            stream_kind=stream_kind,
            stream_id=stream_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=payload,
            sensitivity=sensitivity,
            retention_class=retention_class,
        )
```

Create `core/src/weatherflow/events/__init__.py`:

```python
"""Append-only event contracts."""

from weatherflow.events.models import Actor, Event, RetentionClass, Sensitivity

__all__ = ["Actor", "Event", "RetentionClass", "Sensitivity"]
```

- [ ] **Step 4: Run the tests and verify GREEN**

Run:

```bash
uv run --package weatherflow-core --extra dev pytest \
  core/tests/events/test_event_models.py -q
```

Expected: `2 passed`.

---

### Task 4: Implement the append-only EventLedger with TDD

**Files:**
- Create: `core/tests/events/test_event_ledger.py`
- Create: `core/src/weatherflow/events/repository.py`
- Modify: `core/src/weatherflow/events/__init__.py`

- [ ] **Step 1: Write failing EventLedger tests**

Create `core/tests/events/test_event_ledger.py`:

```python
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

    assert (await ledger.get(event.id)).payload == {"version": 1}


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
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
uv run --package weatherflow-core --extra dev pytest \
  core/tests/events/test_event_ledger.py -q
```

Expected: collection fails because `weatherflow.events.repository` does not
exist.

- [ ] **Step 3: Implement EventLedger**

Create `core/src/weatherflow/events/repository.py`:

```python
import json
import sqlite3
from collections.abc import Sequence
from typing import Any

from weatherflow.events.models import Event
from weatherflow.storage import Database


class DuplicateEventError(ValueError):
    pass


class EventLedger:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def append(self, event: Event) -> None:
        values = (
            event.id,
            event.type,
            event.recorded_at.isoformat(),
            event.actor.value,
            event.stream_kind,
            event.stream_id,
            event.correlation_id,
            event.causation_id,
            json.dumps(event.payload, ensure_ascii=False, separators=(",", ":")),
            event.sensitivity.value,
            event.retention_class.value,
        )
        try:
            async with self.database.connect() as connection:
                await connection.execute(
                    """
                    INSERT INTO events(
                        id, type, recorded_at, actor, stream_kind, stream_id,
                        correlation_id, causation_id, payload, sensitivity,
                        retention_class
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                await connection.commit()
        except sqlite3.IntegrityError as error:
            raise DuplicateEventError(event.id) from error

    async def get(self, event_id: str) -> Event | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute("SELECT * FROM events WHERE id = ?", (event_id,))
            ).fetchone()
        return self._from_row(row) if row else None

    async def list_stream(
        self,
        stream_kind: str,
        stream_id: str,
        *,
        limit: int = 100,
    ) -> list[Event]:
        return await self._list(
            "stream_kind = ? AND stream_id = ?",
            (stream_kind, stream_id),
            limit,
        )

    async def list_correlation(
        self,
        correlation_id: str,
        *,
        limit: int = 100,
    ) -> list[Event]:
        return await self._list("correlation_id = ?", (correlation_id,), limit)

    async def _list(
        self,
        where: str,
        parameters: Sequence[Any],
        limit: int,
    ) -> list[Event]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        query = f"SELECT * FROM events WHERE {where} ORDER BY recorded_at, id LIMIT ?"
        async with self.database.connect() as connection:
            rows = await (await connection.execute(query, (*parameters, limit))).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: Any) -> Event:
        return Event.model_validate(
            {
                "id": row["id"],
                "type": row["type"],
                "recorded_at": row["recorded_at"],
                "actor": row["actor"],
                "stream_kind": row["stream_kind"],
                "stream_id": row["stream_id"],
                "correlation_id": row["correlation_id"],
                "causation_id": row["causation_id"],
                "payload": json.loads(row["payload"]),
                "sensitivity": row["sensitivity"],
                "retention_class": row["retention_class"],
            }
        )
```

- [ ] **Step 4: Export EventLedger**

Replace `core/src/weatherflow/events/__init__.py` with:

```python
"""Append-only event contracts."""

from weatherflow.events.models import Actor, Event, RetentionClass, Sensitivity
from weatherflow.events.repository import DuplicateEventError, EventLedger

__all__ = [
    "Actor",
    "DuplicateEventError",
    "Event",
    "EventLedger",
    "RetentionClass",
    "Sensitivity",
]
```

- [ ] **Step 5: Run the event tests and verify GREEN**

Run:

```bash
uv run --package weatherflow-core --extra dev pytest core/tests/events -q
```

Expected: `6 passed`.

- [ ] **Step 6: Run P1a quality gates**

Run:

```bash
uv run --package weatherflow-core --extra dev ruff check core/src core/tests
uv run --package weatherflow-core --extra dev ruff format --check core/src core/tests
uv run --package weatherflow-core --extra dev pytest core/tests -q
```

Expected: all commands exit 0 and the total suite reports `17 passed`.

- [ ] **Step 7: Commit Event Ledger**

Run:

```bash
git add core/src/weatherflow/events core/tests/events
git diff --cached --check
git commit -m "feat: add append-only Event Ledger"
```

---

### Task 5: Document and audit the P1a boundary

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Update the repository map**

In `AGENTS.md`, replace the current file-map block with:

```text
core/
  src/weatherflow/
    api/             HTTP adapter
    events/          immutable Event envelope and append-only ledger
    storage/         SQLite connection and numbered migrations
  tests/             unit, contract, and integration tests
docs/superpowers/    approved specifications and implementation plans
weatherflow-architecture-v3.md
```

- [ ] **Step 2: Update README current status**

Replace the P0 status paragraph with:

```text
P0 established the clean v3 package, health API, CLI, and quality gates. P1a
adds the WAL-mode SQLite foundation and append-only Event Ledger. Durable Runs,
Trust, Rhythm Intelligence, the desktop shell, and Capability Packs continue in
P1b-P4.
```

- [ ] **Step 3: Run the complete locked gate**

Run:

```bash
uv sync --all-packages --all-extras --locked
make check
git diff --check
```

Expected: locked sync, Ruff, formatting, and all tests pass.

- [ ] **Step 4: Commit documentation**

Run:

```bash
git add AGENTS.md README.md
git diff --cached --check
git commit -m "docs: describe WeatherFlow v3 data foundation"
```

- [ ] **Step 5: Verify P1a acceptance**

Run:

```bash
test -z "$(git status --porcelain)"
make check
git log --oneline -3
```

Expected:

- clean worktree;
- all tests pass;
- latest three commits are documentation, Event Ledger, and SQLite foundation.

P1a ends here. Write P1b before creating Run tables or coordinator code.
