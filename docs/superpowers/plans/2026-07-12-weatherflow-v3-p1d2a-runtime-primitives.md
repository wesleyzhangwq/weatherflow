# WeatherFlow v3 P1d2a Runtime Primitives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define provider-neutral agent-turn contracts and a durable optimistic checkpoint that can resume after process death.

**Architecture:** Domain messages and model outputs contain no provider-specific wire fields. A `ModelAdapter` protocol receives a frozen request and returns a discriminated turn. SQLite stores one versioned checkpoint per Run with compact transcript/state JSON.

**Tech Stack:** Python 3.12, typing.Protocol, Pydantic v2 discriminated unions, SQLite/aiosqlite, pytest-asyncio.

---

## Locked contracts

- Provider wire formats stop at adapter boundaries.
- One model turn returns exactly one of final text, tool call, or delegation request.
- Checkpoints persist bounded domain data and artifact/action references, never live objects.
- Checkpoint updates use expected-version concurrency.
- Workers may be represented in contracts but are marked leaf and cannot delegate.

### Task 1: Provider-neutral turn contracts

**Files:** Create `runtime/{__init__.py,models.py,protocols.py}` and focused tests.

- [ ] Write failing tests for frozen messages, discriminated final/tool/delegation turns, request JSON round-trip with ToolSpecs, invalid multi-kind output rejection, and leaf AgentDefinition delegation prohibition.
- [ ] Implement `MessageRole`, `AgentMessage`, `FinalTurn`, `ToolCallTurn`, `DelegationTurn`, `ModelTurn` discriminated union, `ModelRequest`, `ModelUsage`, `AgentDefinition(is_leaf, tool_filter, max_steps)`, and `CompactWorkerResult`. Implement runtime validation that a leaf definition rejects DelegationTurn.
- [ ] Define async `ModelAdapter.complete(request)` and `ToolExecutor.execute(tool, arguments, context)` protocols plus frozen execution context/result contracts.
- [ ] Verify and commit `feat: define provider-neutral runtime contracts`.

### Task 2: Migration 6 and optimistic checkpoints

**Files:** Add migration 6; create `runtime/checkpoints.py`, `runtime/repository.py`, focused tests; update storage tests/exports.

- [ ] Write failing tests for migration table creation; new checkpoint version 0; create/get; transcript and state round-trip; optimistic append/update; stale-version rollback; and one-checkpoint-per-Run uniqueness.
- [ ] Migration 6 creates `checkpoints(run_id PK/FK, version, step_index, transcript JSON, state JSON, pending_action_id, updated_at)`. Implement frozen `RunCheckpoint` with `new()` and no mutable live fields.
- [ ] Implement repository `create_in`, `get`, `get_in`, and `save_in(checkpoint, expected_version)`; explicit duplicate/not-found/version exceptions; compact canonical JSON.
- [ ] Run focused/full checks; commit `feat: add durable Run checkpoints`.

### Task 3: Document and audit P1d2a

- [ ] Update README/AGENTS runtime map and serialization rule.
- [ ] Run locked sync/full checks; commit `docs: describe WeatherFlow runtime primitives`.

P1d2a ends here. P1d2b implements the shared turn loop and deterministic dispatch over these contracts.
