# WeatherFlow v3 P1c3 Capability Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resolve the smallest authorized tool surface and freeze its exact schemas for the lifetime of a Run.

**Architecture:** An in-memory `CapabilityCatalog` owns current ToolSpecs. A pure resolver applies explicit selection, agent filters, and the Trust Policy. `CapabilitySnapshotCoordinator` persists one immutable snapshot per Run, attaches its ID with optimistic concurrency, and emits an audit event atomically.

**Tech Stack:** Python 3.12, SQLite/aiosqlite, Pydantic v2, SHA-256 canonical JSON, pytest-asyncio.

---

## Locked contracts

- Catalog changes affect new Runs only.
- A Run has at most one capability snapshot.
- Missing requested tool IDs fail closed; unavailable/unauthorized tools are not frozen.
- Snapshot tools are sorted by tool ID and hashed from canonical JSON.
- Attaching a snapshot is versioned and audited in one transaction.

### Task 1: Catalog and pure resolution

**Files:** Create `capabilities/catalog.py`, `capabilities/resolver.py`, and focused tests; modify exports.

- [ ] Write failing tests for duplicate registration rejection, deterministic lookup order, explicit requested IDs, agent allow-filter intersection, missing-tool failure, and Trust Policy removal of unavailable/out-of-scope tools while keeping approval-required tools.
- [ ] Observe RED.
- [ ] Implement `CapabilityCatalog` with `register`, `get`, `select`, and `all`; duplicate IDs raise `DuplicateToolError`, missing selection raises `UnknownToolError`. Implement `CapabilityResolver.resolve(catalog, workspace, requested_tool_ids, allowed_tool_ids=None)` returning an ordered tuple after filter + `SupervisedPolicy.visible()`.
- [ ] Verify and commit `feat: resolve authorized capability surfaces`.

### Task 2: Snapshot model, migration 4, and repository

**Files:** Add migration 4; create `capabilities/snapshots.py`, `capabilities/repository.py`, and tests; modify exports/storage tests.

- [ ] Write failing tests that migration 4 creates `capability_snapshots`; `RunCapabilitySnapshot.freeze()` sorts tools and produces the same SHA-256 digest for identical schemas; repository create/get round-trips nested ToolSpecs; second snapshot for a Run is rejected.
- [ ] Observe RED.
- [ ] Migration 4 creates `capability_snapshots(id PK, run_id UNIQUE FK, catalog_revision, tools JSON, digest, created_at)`. Implement frozen snapshot fields and canonical JSON using sorted keys and compact separators. Implement connection-bound create/get plus `get_by_run_id`; map uniqueness to `DuplicateCapabilitySnapshot`.
- [ ] Verify and commit `feat: persist immutable capability snapshots`.

### Task 3: Atomic snapshot coordinator

**Files:** Extend `RunRepository`; create `capabilities/coordinator.py` and tests; modify exports.

- [ ] Write failing tests that freeze resolves/persists/attaches/audits in one transaction, retry returns the same snapshot without new event, catalog mutation after freeze leaves the stored snapshot unchanged, stale Run version rolls all changes back, and failing ledger append rolls all changes back.
- [ ] Add `RunRepository.attach_capability_snapshot_in(connection, run_id, snapshot_id, expected_version)` which sets the previously-null pointer and increments version; conflicts raise `RunVersionConflict`.
- [ ] Implement `CapabilitySnapshotCoordinator.freeze_for_run(...)`: fast-path existing snapshot, resolve current catalog, build snapshot, recheck in transaction, persist, attach, append `capability.snapshot_frozen` with digest/tool IDs, and return snapshot plus updated Run.
- [ ] Run focused tests, `make check`, and diff checks; commit `feat: freeze per-Run capability snapshots`.

### Task 4: Document and audit P1c3

- [ ] Update README/AGENTS file map and frozen-schema invariant.
- [ ] Run locked sync and full verification; commit `docs: describe WeatherFlow capability snapshots`.

P1c3 ends here. P1d adds Artifact Store and the first resumable shared turn loop/CLI vertical increment.
