# WeatherFlow v3 P1b2 Run Coordinator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist Runs with optimistic concurrency and expose one atomic Coordinator for idempotent creation and audited state transitions.

**Architecture:** `RunRepository` owns SQL mapping and version checks. `RunCoordinator` owns legal transitions and composes repository writes with `EventLedger.append_in()` inside `Database.transaction()`. Every operation performed inside that transaction uses the supplied connection; no nested connection is opened.

**Tech Stack:** Python 3.12, aiosqlite, Pydantic v2, pytest-asyncio.

---

## Locked contracts

- `client_request_id` makes Run creation idempotent.
- `expected_version` is checked before transition legality so stale callers always receive `RunVersionConflict`.
- Invalid or conflicting transitions do not mutate the Run or append audit events.
- The Run write and corresponding Event Ledger append commit or roll back together.
- Only `RunCoordinator` composes state changes with audit events.

### Task 1: Add the optimistic Run repository

**Files:**
- Create: `core/tests/runs/test_run_repository.py`
- Create: `core/src/weatherflow/runs/repository.py`
- Modify: `core/src/weatherflow/runs/__init__.py`

- [ ] **Step 1: Write the failing repository tests**

Create `core/tests/runs/test_run_repository.py` with tests covering:

```python
from pathlib import Path

import pytest

from weatherflow.runs import (
    DuplicateRunError,
    Run,
    RunRepository,
    RunStatus,
    RunVersionConflict,
)
from weatherflow.storage import Database


async def make_repository(tmp_path: Path) -> tuple[Database, RunRepository]:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    return database, RunRepository(database)


async def test_create_round_trips_every_run_field(tmp_path: Path) -> None:
    database, repository = await make_repository(tmp_path)
    run = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )

    async with database.transaction() as connection:
        await repository.create_in(connection, run)

    assert await repository.get(run.id) == run
    assert await repository.get_by_client_request_id("request-1") == run


async def test_duplicate_client_request_id_is_rejected(tmp_path: Path) -> None:
    database, repository = await make_repository(tmp_path)
    first = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    duplicate = Run.new(
        client_request_id="request-1",
        user_intent="another intent",
        workspace_id="workspace-1",
    )

    async with database.transaction() as connection:
        await repository.create_in(connection, first)

    with pytest.raises(DuplicateRunError):
        async with database.transaction() as connection:
            await repository.create_in(connection, duplicate)


async def test_transition_increments_version(tmp_path: Path) -> None:
    database, repository = await make_repository(tmp_path)
    run = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    async with database.transaction() as connection:
        await repository.create_in(connection, run)
        updated = await repository.transition_in(
            connection,
            run.id,
            RunStatus.PLANNING,
            expected_version=0,
        )

    assert updated.status is RunStatus.PLANNING
    assert updated.version == 1
    assert updated.updated_at >= run.updated_at


async def test_stale_version_cannot_overwrite_run(tmp_path: Path) -> None:
    database, repository = await make_repository(tmp_path)
    run = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    async with database.transaction() as connection:
        await repository.create_in(connection, run)
        await repository.transition_in(
            connection,
            run.id,
            RunStatus.PLANNING,
            expected_version=0,
        )

    with pytest.raises(RunVersionConflict):
        async with database.transaction() as connection:
            await repository.transition_in(
                connection,
                run.id,
                RunStatus.RUNNING,
                expected_version=0,
            )

    stored = await repository.get(run.id)
    assert stored is not None
    assert stored.status is RunStatus.PLANNING
    assert stored.version == 1
```

- [ ] **Step 2: Run RED**

Run:

```bash
uv run --package weatherflow-core --extra dev pytest core/tests/runs/test_run_repository.py -q
```

Expected: collection fails because repository exports do not exist.

- [ ] **Step 3: Implement the repository**

Create `core/src/weatherflow/runs/repository.py` with these concrete contracts:

```python
import sqlite3
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from weatherflow.runs.models import Run, RunBudget, RunStatus
from weatherflow.storage import Database


class DuplicateRunError(ValueError):
    pass


class RunNotFoundError(LookupError):
    pass


class RunVersionConflict(RuntimeError):
    pass


class RunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_in(self, connection: aiosqlite.Connection, run: Run) -> None:
        try:
            await connection.execute(
                """
                INSERT INTO runs(
                    id, client_request_id, user_intent, workspace_id, status,
                    version, created_at, updated_at, rhythm_snapshot_id,
                    capability_snapshot_id, policy_profile, budget,
                    checkpoint_ref, result_summary, error_class, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(run),
            )
        except sqlite3.IntegrityError as error:
            raise DuplicateRunError(run.client_request_id) from error

    async def get(self, run_id: str) -> Run | None:
        async with self.database.connect() as connection:
            return await self.get_in(connection, run_id)

    async def get_in(
        self, connection: aiosqlite.Connection, run_id: str
    ) -> Run | None:
        row = await (
            await connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        ).fetchone()
        return self._from_row(row) if row else None

    async def get_by_client_request_id(self, value: str) -> Run | None:
        async with self.database.connect() as connection:
            return await self.get_by_client_request_id_in(connection, value)

    async def get_by_client_request_id_in(
        self, connection: aiosqlite.Connection, value: str
    ) -> Run | None:
        row = await (
            await connection.execute(
                "SELECT * FROM runs WHERE client_request_id = ?", (value,)
            )
        ).fetchone()
        return self._from_row(row) if row else None

    async def transition_in(
        self,
        connection: aiosqlite.Connection,
        run_id: str,
        target: RunStatus,
        expected_version: int,
        *,
        result_summary: str | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> Run:
        current = await self.get_in(connection, run_id)
        if current is None:
            raise RunNotFoundError(run_id)
        if current.version != expected_version:
            raise RunVersionConflict(run_id)
        current.status.require_transition(target)
        updated_at = datetime.now(UTC)
        cursor = await connection.execute(
            """
            UPDATE runs
            SET status = ?, version = version + 1, updated_at = ?,
                result_summary = ?, error_class = ?, error_message = ?
            WHERE id = ? AND version = ?
            """,
            (
                target.value,
                updated_at.isoformat(),
                result_summary,
                error_class,
                error_message,
                run_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise RunVersionConflict(run_id)
        updated = await self.get_in(connection, run_id)
        if updated is None:
            raise RunNotFoundError(run_id)
        return updated

    @staticmethod
    def _values(run: Run) -> tuple[Any, ...]:
        return (
            run.id,
            run.client_request_id,
            run.user_intent,
            run.workspace_id,
            run.status.value,
            run.version,
            run.created_at.isoformat(),
            run.updated_at.isoformat(),
            run.rhythm_snapshot_id,
            run.capability_snapshot_id,
            run.policy_profile,
            run.budget.model_dump_json(),
            run.checkpoint_ref,
            run.result_summary,
            run.error_class,
            run.error_message,
        )

    @staticmethod
    def _from_row(row: Any) -> Run:
        return Run.model_validate(
            {
                "id": row["id"],
                "client_request_id": row["client_request_id"],
                "user_intent": row["user_intent"],
                "workspace_id": row["workspace_id"],
                "status": row["status"],
                "version": row["version"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "rhythm_snapshot_id": row["rhythm_snapshot_id"],
                "capability_snapshot_id": row["capability_snapshot_id"],
                "policy_profile": row["policy_profile"],
                "budget": RunBudget.model_validate_json(row["budget"]),
                "checkpoint_ref": row["checkpoint_ref"],
                "result_summary": row["result_summary"],
                "error_class": row["error_class"],
                "error_message": row["error_message"],
            }
        )
```

Export `DuplicateRunError`, `RunNotFoundError`, `RunRepository`, and
`RunVersionConflict` from `weatherflow.runs`.

- [ ] **Step 4: Run GREEN and quality checks**

```bash
uv run --package weatherflow-core --extra dev pytest core/tests/runs/test_run_repository.py -q
uv run --package weatherflow-core --extra dev ruff check core/src core/tests
uv run --package weatherflow-core --extra dev ruff format --check core/src core/tests
```

- [ ] **Step 5: Commit**

```bash
git add core/src/weatherflow/runs core/tests/runs/test_run_repository.py
git commit -m "feat: add optimistic Run repository"
```

### Task 2: Add connection-bound Event Ledger reads

**Files:**
- Modify: `core/src/weatherflow/events/repository.py`
- Modify: `core/tests/events/test_event_ledger.py`

- [ ] **Step 1: Add a failing transaction-bound read test**

Append to `core/tests/events/test_event_ledger.py`:

```python
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
```

- [ ] **Step 2: Run RED**

```bash
uv run --package weatherflow-core --extra dev pytest core/tests/events/test_event_ledger.py -q
```

Expected: `EventLedger` has no `list_stream_in`.

- [ ] **Step 3: Implement without opening a nested connection**

Add:

```python
    async def list_stream_in(
        self,
        connection: aiosqlite.Connection,
        stream_kind: str,
        stream_id: str,
        *,
        limit: int = 100,
    ) -> list[Event]:
        return await self._list_in(
            connection,
            "stream_kind = ? AND stream_id = ?",
            (stream_kind, stream_id),
            limit,
        )

    async def _list_in(
        self,
        connection: aiosqlite.Connection,
        where: str,
        parameters: Sequence[Any],
        limit: int,
    ) -> list[Event]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        query = f"SELECT * FROM events WHERE {where} ORDER BY recorded_at, id LIMIT ?"
        rows = await (await connection.execute(query, (*parameters, limit))).fetchall()
        return [self._from_row(row) for row in rows]
```

Refactor `_list()` to open one connection and delegate to `_list_in()`.

- [ ] **Step 4: Run GREEN and commit**

```bash
uv run --package weatherflow-core --extra dev pytest core/tests/events/test_event_ledger.py -q
git add core/src/weatherflow/events/repository.py core/tests/events/test_event_ledger.py
git commit -m "feat: add transaction-bound event reads"
```

### Task 3: Add the atomic Run Coordinator

**Files:**
- Create: `core/tests/runs/test_run_coordinator.py`
- Create: `core/src/weatherflow/runs/coordinator.py`
- Modify: `core/src/weatherflow/runs/__init__.py`

- [ ] **Step 1: Write failing behavior tests**

Create `core/tests/runs/test_run_coordinator.py`:

```python
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
    async def append_in(
        self, connection: aiosqlite.Connection, event: Event
    ) -> None:
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
    assert [event.type for event in await ledger.list_stream("run", run.id)] == [
        "run.created"
    ]
```

- [ ] **Step 2: Run RED**

```bash
uv run --package weatherflow-core --extra dev pytest core/tests/runs/test_run_coordinator.py -q
```

Expected: `RunCoordinator` export is missing.

- [ ] **Step 3: Implement the coordinator**

Create `core/src/weatherflow/runs/coordinator.py`:

```python
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs.models import Run, RunStatus
from weatherflow.runs.repository import RunNotFoundError, RunRepository
from weatherflow.storage import Database


class RunCoordinator:
    def __init__(
        self,
        database: Database,
        repository: RunRepository,
        ledger: EventLedger,
    ) -> None:
        self.database = database
        self.repository = repository
        self.ledger = ledger

    async def create_run(
        self,
        *,
        client_request_id: str,
        user_intent: str,
        workspace_id: str,
    ) -> Run:
        existing = await self.repository.get_by_client_request_id(client_request_id)
        if existing is not None:
            return existing
        run = Run.new(
            client_request_id=client_request_id,
            user_intent=user_intent,
            workspace_id=workspace_id,
        )
        async with self.database.transaction() as connection:
            existing = await self.repository.get_by_client_request_id_in(
                connection, client_request_id
            )
            if existing is not None:
                return existing
            await self.repository.create_in(connection, run)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="run.created",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=run.id,
                    correlation_id=run.id,
                    payload={
                        "client_request_id": client_request_id,
                        "workspace_id": workspace_id,
                        "status": run.status.value,
                    },
                ),
            )
        return run

    async def transition(
        self,
        *,
        run_id: str,
        target: RunStatus,
        expected_version: int,
        result_summary: str | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> Run:
        async with self.database.transaction() as connection:
            current = await self.repository.get_in(connection, run_id)
            if current is None:
                raise RunNotFoundError(run_id)
            prior = await self.ledger.list_stream_in(connection, "run", run_id)
            updated = await self.repository.transition_in(
                connection,
                run_id,
                target,
                expected_version,
                result_summary=result_summary,
                error_class=error_class,
                error_message=error_message,
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="run.status_changed",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=run_id,
                    correlation_id=run_id,
                    causation_id=prior[-1].id if prior else None,
                    payload={
                        "from": current.status.value,
                        "to": target.value,
                        "version": updated.version,
                    },
                ),
            )
        return updated
```

Export `RunCoordinator` from `weatherflow.runs`.

- [ ] **Step 4: Run GREEN and full regressions**

```bash
uv run --package weatherflow-core --extra dev pytest core/tests/runs/test_run_coordinator.py -q
make check
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add core/src/weatherflow/runs core/tests/runs/test_run_coordinator.py
git commit -m "feat: add atomic Run Coordinator"
```

### Task 4: Document and audit P1b2

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`

- [ ] Update the `runs/` file-map description to “Run model, optimistic repository, sole state coordinator”.
- [ ] Record P1b2 idempotency, optimistic concurrency, and atomic audit behavior in README status.
- [ ] Run `uv sync --package weatherflow-core --extra dev --locked`, `make check`, `git diff --check`, and `git status --short`.
- [ ] Commit documentation with `docs: describe WeatherFlow Run coordination`.

P1b2 ends here. Write and commit the P1c plan before Workspace, Capability,
Policy, or Approval implementation.
