# WeatherFlow v3 P1c2b Approval Coordinator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Atomically persist proposed side effects, park Runs for human approval, and resume or suspend them after a durable decision.

**Architecture:** `ApprovalCoordinator` is the sole composition boundary for Action + Approval + Run + Event Ledger. It repeats `SupervisedPolicy` before persistence. `RunCoordinator.transition_in()` retains sole ownership of Run transitions while allowing a caller-owned transaction.

**Tech Stack:** Python 3.12, aiosqlite, Pydantic v2, pytest-asyncio.

---

## Locked contracts

- Proposed side effects exist durably before a Run enters WAITING_APPROVAL.
- A repeated idempotency key returns the existing Action/Approval without duplicate events.
- Approve and deny both resume the Run to RUNNING; approval is not execution.
- Approval expiry cancels the unexecuted Action and suspends the Run in PAUSED.
- Policy is evaluated again at proposal time; non-APPROVE decisions cannot enter this path.
- Every multi-record change and its audit events share one transaction.

### Task 1: Add composable Run transitions and timeout state paths

**Files:** Modify `runs/models.py`, `runs/coordinator.py`, and their tests.

- [ ] Add failing tests that WAITING_APPROVAL may transition to PAUSED; Action PROPOSED may transition to new terminal CANCELLED; and `RunCoordinator.transition_in(connection, ...)` makes the same Run update/audit event visible inside a caller transaction.
- [ ] Observe RED.
- [ ] Add `ActionStatus.CANCELLED`; add PROPOSED -> CANCELLED. Add WAITING_APPROVAL -> PAUSED. Refactor `RunCoordinator.transition()` to open a transaction and delegate to public connection-bound `transition_in()` containing the existing repository + audit logic.
- [ ] Run focused and regression tests; commit `feat: make Run transitions transaction-composable`.

### Task 2: ApprovalCoordinator proposal flow

**Files:** Create `trust/coordinator.py`, `tests/trust/test_approval_coordinator.py`; modify exports.

- [ ] Write failing tests that build a RUNNING Run and assert: an external-write ToolSpec produces one Action, one pending Approval, a WAITING_APPROVAL Run, and ordered audit events; repeating the idempotency key returns the same records and no new events; a missing-scope tool is rejected with `ApprovalPolicyError` and changes nothing; an observe tool is rejected because it does not require approval.
- [ ] Observe missing export RED.
- [ ] Implement frozen `ApprovalBundle(action, approval, run)`. `ApprovalCoordinator.propose()` accepts Run ID/version, ToolSpec, Workspace, arguments, idempotency key, and preview. Evaluate `SupervisedPolicy`; require APPROVE. Fast-path existing idempotency keys, then recheck inside `Database.transaction()`. Create Action and Approval, append `action.proposed` and `approval.requested`, and call `RunCoordinator.transition_in(...WAITING_APPROVAL...)` in the same transaction. Return the bundle.
- [ ] Run focused tests and quality checks; commit `feat: atomically request side-effect approval`.

### Task 3: Approval decision and expiry flows

**Files:** Extend coordinator and its tests.

- [ ] Add failing tests proving approve transitions Approval -> APPROVED, Action -> APPROVED, Run -> RUNNING; deny transitions Approval -> DENIED, Action -> DENIED, Run -> RUNNING; expiry transitions Approval -> EXPIRED, Action -> CANCELLED, Run -> PAUSED; a repeated identical decision is idempotent; and a failing audit append rolls every record back.
- [ ] Implement `decide(approval_id, expected_version, approved, decided_by, rationale)` and `expire(approval_id, expected_version)`. Load all records on the same connection. Identical terminal decisions return the current bundle; conflicting terminal decisions raise `ApprovalAlreadyDecided`. Append `approval.decided` or `approval.expired`, then use `RunCoordinator.transition_in()` for the Run event. Never invoke a tool.
- [ ] Run focused tests, `make check`, and `git diff --check`; commit `feat: coordinate durable approval decisions`.

### Task 4: Document and audit P1c2b

- [ ] Update README and AGENTS with the sole approval coordination path and timeout semantics.
- [ ] Run locked sync, `make check`, diff/status checks.
- [ ] Commit `docs: describe WeatherFlow approval coordination`.

P1c2b ends here. P1c3 freezes per-Run capability snapshots; tool execution remains deferred until the shared turn-loop plan.
