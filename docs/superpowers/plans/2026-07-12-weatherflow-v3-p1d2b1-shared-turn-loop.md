# WeatherFlow v3 P1d2b1 Shared Turn Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Execute provider-neutral model turns, safe tools, final results, and approval parking through one resumable loop.

**Architecture:** `SharedTurnLoop` loads the frozen capability snapshot and checkpoint, advances the Run via RunCoordinator, persists every model turn before dispatch, repeats Trust Policy, and either executes safe tools, parks approval-required actions, or commits a final result. Approved-action execution is deferred to P1d2b2.

**Tech Stack:** Python 3.12, async protocols, Pydantic TypeAdapter, SQLite transactions, pytest-asyncio.

---

## Locked contracts

- No tool outside the frozen snapshot is callable.
- Every model turn is checkpointed before tool dispatch.
- Trust Policy is repeated immediately before dispatch.
- ALLOW/SANDBOX tools execute; APPROVE tools persist/park; DENY/HIDE become bounded observations.
- Final content and SUCCEEDED transition commit atomically.
- Step and Run budgets stop the loop deterministically.

### Task 1: Runtime outcomes and safe-tool registry

**Files:** Create `runtime/tools.py`, `runtime/outcomes.py`, focused tests; modify exports.

- [ ] Write failing tests for duplicate/missing executor IDs, frozen `LoopOutcome` variants succeeded/waiting_approval/failed, and output-size truncation that preserves structured validity.
- [ ] Implement `ToolExecutorRegistry` mapping IDs to executors without authority semantics; `BoundedObservation` normalization; and frozen `LoopOutcome` with Run/result/action references.
- [ ] Verify and commit `feat: add runtime dispatch primitives`.

### Task 2: SharedTurnLoop happy path and safe tools

**Files:** Create `runtime/loop.py` and integration tests.

- [ ] Using scripted fake model/executors, write failing tests for: QUEUED -> PLANNING -> RUNNING -> SUCCEEDED final answer; checkpoint creation and persisted final transcript; safe observe tool result fed to the next model turn; unknown snapshot tool becomes an error observation without executor call; max-step exhaustion -> FAILED.
- [ ] Implement checkpoint initialization from `run.user_intent`, state advancement, frozen snapshot lookup, ModelRequest construction, model turn validation, and transaction-bound checkpoint/event/Run updates. Persist `runtime.turn_recorded`, `tool.executed`, and `run.result_committed` events.
- [ ] Verify and commit `feat: execute the shared safe-turn loop`.

### Task 3: Approval parking path

**Files:** Extend loop and integration tests.

- [ ] Add failing test where model requests external_write: loop calls ApprovalCoordinator with stable idempotency key derived from Run + step/call ID, checkpoint stores pending action, returns WAITING_APPROVAL, and executor is never called. Retrying loop while approval is pending returns same outcome without a new model call/event.
- [ ] Implement APPROVE dispatch using existing ApprovalCoordinator; persist pending action reference in checkpoint after proposal and return typed outcome. DENY/HIDE observations remain inside the loop.
- [ ] Run focused/full checks; commit `feat: park approval-required runtime actions`.

### Task 4: Document and audit P1d2b1

- [ ] Update README/AGENTS sole-loop and checkpoint-before-dispatch invariants.
- [ ] Run locked sync/full checks; commit `docs: describe WeatherFlow shared turn loop`.

P1d2b1 ends here. P1d2b2 executes approved Actions idempotently and routes uncertain recovery to NEEDS_REVIEW.
