# WeatherFlow v3 P1c2a Approval Primitives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add durable, immutable Action and Approval records with idempotent creation and optimistic status updates.

**Architecture:** An Action is the durable proposed side effect; an Approval is the human decision record for one Action. Separate repositories own SQL and version checks. Coordination with Run state is deliberately deferred to P1c2b so this increment stays independently verifiable.

**Tech Stack:** Python 3.12, SQLite/aiosqlite, Pydantic v2, python-ulid, pytest-asyncio.

---

## Locked contracts

- Every proposed side effect has a stable `action_id` and unique `idempotency_key` before approval is requested.
- One Action has at most one Approval.
- Mutable operational status uses optimistic `expected_version` checks.
- Arguments and previews are structured JSON; credentials are forbidden by higher layers and never modeled as values here.
- Approval status and Action execution status are separate state machines.

### Task 1: Migration 3 and domain models

**Files:** Modify `storage/migrations.py`; create `trust/models.py`; modify `trust/__init__.py`; create `tests/trust/test_approval_models.py` and extend `tests/storage/test_database.py`.

- [ ] Write failing tests proving migration 3 creates `actions` and `approvals`; `Action.new()` is PROPOSED/version 0 with ULID and stable idempotency key; `Approval.for_action()` is PENDING/version 0; all terminal Action/Approval statuses reject transitions; and legal transitions are deterministic.
- [ ] Observe RED before implementation.
- [ ] Add migration 3. `actions` contains `id`, `run_id` FK, `tool_id`, JSON `arguments`, `effect`, `status`, unique `idempotency_key`, JSON `preview`, timestamps, `version`, nullable JSON `result`, and nullable error fields. `approvals` contains `id`, unique `action_id` FK, `run_id` FK, `status`, timestamps, `decided_by`, `rationale`, and `version`. Add run/status indexes.
- [ ] Implement frozen `ActionStatus`: proposed, approved, denied, executing, succeeded, failed, needs_review. Legal paths: proposed -> approved/denied; approved -> executing; executing -> succeeded/failed/needs_review; terminal statuses have no exits. Implement frozen `ApprovalStatus`: pending, approved, denied, expired, cancelled; pending may transition to any terminal status. Add typed invalid-transition errors.
- [ ] Implement frozen `Action` and `Approval` models with class constructors and UTC timestamps. Run focused tests and quality checks; commit `feat: define durable approval primitives`.

### Task 2: ActionRepository

**Files:** Create `trust/action_repository.py` and `tests/trust/test_action_repository.py`; modify exports.

- [ ] Write failing async tests for connection-bound create/get round-trip, lookup by idempotency key, duplicate-key rejection, legal versioned transition, and stale-version rollback.
- [ ] Observe missing export RED.
- [ ] Implement `ActionRepository.create_in`, `get`, `get_in`, `get_by_idempotency_key`, `get_by_idempotency_key_in`, and `transition_in`. Map unique violations to `DuplicateActionError`, missing IDs to `ActionNotFoundError`, stale updates to `ActionVersionConflict`. Serialize arguments/preview/result as compact UTF-8 JSON.
- [ ] Run focused tests and quality checks; commit `feat: add optimistic Action repository`.

### Task 3: ApprovalRepository

**Files:** Create `trust/approval_repository.py` and `tests/trust/test_approval_repository.py`; modify exports.

- [ ] Write failing async tests for connection-bound create/get round-trip, lookup by action, duplicate action rejection, approve with actor/rationale and version increment, and stale-version rollback.
- [ ] Observe missing export RED.
- [ ] Implement `ApprovalRepository.create_in`, `get`, `get_in`, `get_by_action_id`, `get_by_action_id_in`, and `transition_in`. Transition records UTC `decided_at`, `decided_by`, `rationale`; map duplicates, missing IDs, and version conflicts to explicit exceptions.
- [ ] Run focused tests, `make check`, and `git diff --check`; commit `feat: add optimistic Approval repository`.

### Task 4: Audit P1c2a

- [ ] Update README and AGENTS file map with separate Action/Approval operational state.
- [ ] Run locked sync, `make check`, `git diff --check`, and status review.
- [ ] Commit `docs: describe WeatherFlow approval primitives`.

P1c2a ends here. P1c2b atomically parks/decides/resumes Runs and appends audit events through the Run Coordinator.
