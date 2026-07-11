# WeatherFlow v3 P1d2b2 Approved Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Execute approved side effects exactly once when possible and route ambiguous crash recovery to NEEDS_REVIEW.

**Architecture:** `ActionExecutionCoordinator` repeats policy, durably marks an Action EXECUTING before invoking its executor, then records SUCCEEDED or a definitive FAILED result. Encountering an already-EXECUTING action after restart is ambiguous and atomically marks both Action and Run NEEDS_REVIEW; no automatic retry occurs.

**Tech Stack:** Python 3.12, async protocols, SQLite transactions, pytest-asyncio.

---

## Locked contracts

- Only APPROVED Actions execute.
- Policy and frozen ToolSpec are checked again immediately before execution.
- EXECUTING is committed before crossing the side-effect boundary.
- Process recovery never retries an EXECUTING external action automatically.
- Result persistence precedes the next model turn.
- Approval itself never counts as execution.

### Task 1: ActionExecutionCoordinator

**Files:** Create `runtime/action_execution.py`, focused tests; modify exports.

- [ ] Write failing tests for approved -> executing -> succeeded with one executor call; unapproved refusal; policy mismatch refusal; definitive executor error -> FAILED; unexpected/ambiguous error -> NEEDS_REVIEW; entering with EXECUTING -> Action and Run NEEDS_REVIEW without executor call; audit failure rollback before executor call.
- [ ] Implement `DefinitiveToolError`, frozen `ActionExecutionOutcome`, and coordinator. Preflight loads Action/Run, requires APPROVED and APPROVE policy, commits EXECUTING + `action.execution_started`, invokes executor with action/idempotency context, then commits terminal Action event. Ambiguous paths also transition Run through RunCoordinator.
- [ ] Verify and commit `feat: execute approved Actions with recovery guards`.

### Task 2: Resume approved turns in SharedTurnLoop

**Files:** Extend loop and integration tests.

- [ ] Add failing integration tests: pending approval returns WAITING; after `ApprovalCoordinator.decide(approved=True)`, rerunning loop executes once, records observation, clears pending action, and reaches final answer; denied action becomes a denial observation without executor call; simulated EXECUTING recovery returns NEEDS_REVIEW and does not call model.
- [ ] Inject ActionExecutionCoordinator. On APPROVE turn, inspect idempotent proposal bundle: pending parks; approved executes and checkpoints result before continuing; denied/cancelled/expired records observation; executing invokes recovery guard. Add NEEDS_REVIEW loop outcome.
- [ ] Run full checks; commit `feat: resume shared loop after approval`.

### Task 3: Document and audit P1d2b2

- [ ] Update README/AGENTS with side-effect recovery invariant.
- [ ] Run locked sync/full checks; commit `docs: describe WeatherFlow approved execution`.

P1d2b2 ends here. P1d3 exposes the durable Run through local API/CLI and proves daemon restart recovery.
