# WeatherFlow v3 P1b1 Run Primitives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add transaction composition, the complete immutable Run model, deterministic transition rules, and migration 2 as the prerequisites for Run persistence.

**Architecture:** `Database.transaction()` and `EventLedger.append_in()` create the atomic composition seam. Migration 2 adds the `runs` table, while immutable Run types define every legal transition before persistence is introduced. Repository and Coordinator work is deliberately deferred to P1b2.

**Tech Stack:** Python 3.12, aiosqlite, Pydantic v2, python-ulid, pytest-asyncio.

---

## Locked contracts

- Statuses: QUEUED, PLANNING, RUNNING, WAITING_APPROVAL, WAITING_USER,
  PAUSED, NEEDS_REVIEW, SUCCEEDED, FAILED, CANCELLED.
- Terminal statuses never transition.
- `client_request_id` is unique and makes create idempotent.
- Every transition checks `expected_version`; conflicts never overwrite.
- Create/transition and corresponding Event Ledger append are one transaction.
- Coordinator, not repository callers or models, decides allowed transitions.

### Task 1: Add transaction composition to Database and EventLedger

**Files:**
- Modify: `core/src/weatherflow/storage/database.py`
- Modify: `core/src/weatherflow/events/repository.py`
- Create: `core/tests/storage/test_transaction.py`

- [ ] **Step 1: Write failing transaction tests**

```python
from pathlib import Path

import pytest

from weatherflow.events import Actor, Event, EventLedger
from weatherflow.storage import Database


async def test_transaction_rolls_back_event_on_error(tmp_path: Path) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    ledger = EventLedger(database)
    event = Event.new(type="test", actor=Actor.SYSTEM, stream_kind="test",
                      stream_id="1", correlation_id="1", payload={})

    with pytest.raises(RuntimeError):
        async with database.transaction() as connection:
            await ledger.append_in(connection, event)
            raise RuntimeError("rollback")

    assert await ledger.get(event.id) is None


async def test_transaction_commits_event(tmp_path: Path) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    ledger = EventLedger(database)
    event = Event.new(type="test", actor=Actor.SYSTEM, stream_kind="test",
                      stream_id="1", correlation_id="1", payload={})

    async with database.transaction() as connection:
        await ledger.append_in(connection, event)

    assert await ledger.get(event.id) == event
```

- [ ] **Step 2: Run RED**

Run: `uv run --package weatherflow-core --extra dev pytest core/tests/storage/test_transaction.py -q`

Expected: failures because `transaction` and `append_in` do not exist.

- [ ] **Step 3: Implement transaction()**

Add to `Database`:

```python
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                await connection.rollback()
                raise
            else:
                await connection.commit()
```

- [ ] **Step 4: Refactor EventLedger append**

Add `import aiosqlite`. Make `append()` open a transaction and delegate to:

```python
    async def append_in(self, connection: aiosqlite.Connection, event: Event) -> None:
        values = self._values(event)
        try:
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
        except sqlite3.IntegrityError as error:
            raise DuplicateEventError(event.id) from error

    @staticmethod
    def _values(event: Event) -> tuple[Any, ...]:
        return (
            event.id, event.type, event.recorded_at.isoformat(), event.actor.value,
            event.stream_kind, event.stream_id, event.correlation_id,
            event.causation_id,
            json.dumps(event.payload, ensure_ascii=False, separators=(",", ":")),
            event.sensitivity.value, event.retention_class.value,
        )
```

`append()` becomes:

```python
    async def append(self, event: Event) -> None:
        async with self.database.transaction() as connection:
            await self.append_in(connection, event)
```

- [ ] **Step 5: Run GREEN and regressions**

Run:

```bash
uv run --package weatherflow-core --extra dev pytest core/tests/storage/test_transaction.py -q
uv run --package weatherflow-core --extra dev pytest core/tests/events -q
```

Expected: 2 transaction tests and 6 event tests pass.

- [ ] **Step 6: Commit**

```bash
git add core/src/weatherflow/storage/database.py core/src/weatherflow/events/repository.py core/tests/storage/test_transaction.py
git commit -m "feat: add atomic database transactions"
```

### Task 2: Add Run model, state machine, and migration 2

**Files:**
- Modify: `core/src/weatherflow/storage/migrations.py`
- Create: `core/src/weatherflow/runs/__init__.py`
- Create: `core/src/weatherflow/runs/models.py`
- Create: `core/tests/runs/test_run_models.py`

- [ ] **Step 1: Write failing model tests**

```python
import pytest

from weatherflow.runs import InvalidTransitionError, Run, RunStatus


def test_new_run_is_queued_with_zero_version() -> None:
    run = Run.new(client_request_id="request-1", user_intent="ship release",
                  workspace_id="workspace-1")
    assert run.status is RunStatus.QUEUED
    assert run.version == 0
    assert len(run.id) == 26


@pytest.mark.parametrize("target", [RunStatus.PLANNING, RunStatus.CANCELLED])
def test_queued_run_allows_declared_transitions(target: RunStatus) -> None:
    assert RunStatus.QUEUED.can_transition_to(target)


def test_terminal_run_rejects_transition() -> None:
    with pytest.raises(InvalidTransitionError):
        RunStatus.SUCCEEDED.require_transition(RunStatus.RUNNING)
```

- [ ] **Step 2: Run RED**

Run: `uv run --package weatherflow-core --extra dev pytest core/tests/runs/test_run_models.py -q`

Expected: missing `weatherflow.runs`.

- [ ] **Step 3: Add migration 2**

Append to `MIGRATIONS`:

```python
    Migration(
        version=2,
        sql="""
        CREATE TABLE runs (
            id TEXT PRIMARY KEY,
            client_request_id TEXT NOT NULL UNIQUE,
            user_intent TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            status TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            rhythm_snapshot_id TEXT,
            capability_snapshot_id TEXT,
            policy_profile TEXT NOT NULL,
            budget TEXT NOT NULL,
            checkpoint_ref TEXT,
            result_summary TEXT,
            error_class TEXT,
            error_message TEXT
        );
        CREATE INDEX idx_runs_status ON runs(status, updated_at);
        """,
    ),
```

- [ ] **Step 4: Implement Run model**

Create `core/src/weatherflow/runs/models.py`:

```python
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID


class InvalidTransitionError(ValueError):
    pass


class RunStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_USER = "waiting_user"
    PAUSED = "paused"
    NEEDS_REVIEW = "needs_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def can_transition_to(self, target: "RunStatus") -> bool:
        return target in TRANSITIONS[self]

    def require_transition(self, target: "RunStatus") -> None:
        if not self.can_transition_to(target):
            raise InvalidTransitionError(f"{self.value} -> {target.value}")


TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.PLANNING, RunStatus.CANCELLED}),
    RunStatus.PLANNING: frozenset({RunStatus.RUNNING, RunStatus.WAITING_USER,
                                   RunStatus.PAUSED, RunStatus.FAILED,
                                   RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset({RunStatus.WAITING_APPROVAL,
                                  RunStatus.WAITING_USER, RunStatus.PAUSED,
                                  RunStatus.NEEDS_REVIEW, RunStatus.SUCCEEDED,
                                  RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.WAITING_APPROVAL: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.WAITING_USER: frozenset({RunStatus.PLANNING, RunStatus.RUNNING,
                                       RunStatus.CANCELLED}),
    RunStatus.PAUSED: frozenset({RunStatus.PLANNING, RunStatus.RUNNING,
                                 RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.NEEDS_REVIEW: frozenset({RunStatus.RUNNING, RunStatus.FAILED,
                                       RunStatus.CANCELLED}),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


class RunBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_steps: int = Field(default=20, ge=1)
    max_cost_usd: float | None = Field(default=None, ge=0)
    timeout_seconds: int = Field(default=1800, ge=1)


class Run(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    client_request_id: str
    user_intent: str
    workspace_id: str
    status: RunStatus
    version: int
    created_at: datetime
    updated_at: datetime
    rhythm_snapshot_id: str | None = None
    capability_snapshot_id: str | None = None
    policy_profile: str = "supervised"
    budget: RunBudget = RunBudget()
    checkpoint_ref: str | None = None
    result_summary: str | None = None
    error_class: str | None = None
    error_message: str | None = None

    @classmethod
    def new(cls, *, client_request_id: str, user_intent: str,
            workspace_id: str) -> "Run":
        now = datetime.now(UTC)
        return cls(id=str(ULID()), client_request_id=client_request_id,
                   user_intent=user_intent, workspace_id=workspace_id,
                   status=RunStatus.QUEUED, version=0, created_at=now,
                   updated_at=now)
```

Create `core/src/weatherflow/runs/__init__.py`:

```python
"""Durable Run contracts and deterministic transitions."""

from weatherflow.runs.models import InvalidTransitionError, Run, RunBudget, RunStatus

__all__ = ["InvalidTransitionError", "Run", "RunBudget", "RunStatus"]
```

- [ ] **Step 5: Run GREEN and migration regression**

Run:

```bash
uv run --package weatherflow-core --extra dev pytest core/tests/runs/test_run_models.py -q
uv run --package weatherflow-core --extra dev pytest core/tests/storage -q
```

Expected: model tests pass; migration count assertions are updated from 1 to 2
in existing storage tests and then all storage tests pass.

- [ ] **Step 6: Commit**

```bash
git add core/src/weatherflow/runs core/src/weatherflow/storage/migrations.py core/tests/runs core/tests/storage/test_database.py
git commit -m "feat: define durable Run state machine"
```

### Task 3: Document and audit P1b1

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`

- [ ] **Step 1: Add `runs/` to the file map**

Describe it as `immutable Run model and deterministic transition rules`.

- [ ] **Step 2: Update README current status**

State that P1b1 adds atomic transaction composition plus Run schema and
transition rules; persistence, coordination, Trust, and Agent execution remain
pending.

- [ ] **Step 3: Verify and commit**

```bash
uv sync --all-packages --all-extras --locked
make check
git diff --check
git add AGENTS.md README.md
git commit -m "docs: describe WeatherFlow Run primitives"
test -z "$(git status --porcelain)"
```

P1b1 ends here. Write P1b2 before adding RunRepository or RunCoordinator code.
