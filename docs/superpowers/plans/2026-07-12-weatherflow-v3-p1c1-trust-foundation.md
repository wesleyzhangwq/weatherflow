# WeatherFlow v3 P1c1 Trust Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define immutable Workspace, ToolSpec, and supervised Trust Policy contracts so authority can be evaluated deterministically before any tool is shown or executed.

**Architecture:** Workspace is the authority boundary. ToolSpec describes capability but grants no authority. `SupervisedPolicy` intersects required scopes with Workspace grants and returns a typed decision. The same pure evaluation method will be reused by capability visibility and the later execution layer.

**Tech Stack:** Python 3.12, Pydantic v2, pathlib, pytest.

---

## Locked contracts

- Capability and authority remain separate.
- Workspace internal storage is never an ordinary action root.
- Missing scopes fail closed.
- Default effects map exactly to: observe/network_read allow; workspace_write/execute sandbox; external_write/install/destructive/sensitive approve.
- Unknown effects cannot enter a valid ToolSpec.
- Approval-required tools remain representable; policy does not execute them.

### Task 1: Workspace authority model

**Files:** Create `core/src/weatherflow/workspaces/{__init__.py,models.py}` and `core/tests/workspaces/test_workspace.py`.

- [ ] Write failing tests proving `Workspace.new()` creates a ULID, freezes granted scopes, accepts paths under action roots, rejects paths outside roots, and always rejects its internal root even if a parent action root was configured.
- [ ] Run `uv run --package weatherflow-core --extra dev pytest core/tests/workspaces/test_workspace.py -q` and observe missing-module RED.
- [ ] Implement frozen `NetworkPolicy(StrEnum)` values `offline`, `declared`, `open`, and frozen `Workspace` fields: `id`, `name`, `action_roots`, `internal_root`, `artifact_root`, `granted_scopes`, `network_policy`, `installed_packs`, `agent_definitions`, `policy_profile`. `Workspace.new()` uses ULID and tuple/frozenset normalization. `allows_action_path()` resolves paths without requiring existence, rejects `internal_root` and descendants first, then accepts only an action-root descendant.
- [ ] Export the types, run focused tests plus Ruff/format checks, and commit `feat: define Workspace authority boundary`.

### Task 2: Canonical ToolSpec

**Files:** Create `core/src/weatherflow/capabilities/{__init__.py,models.py}` and `core/tests/capabilities/test_tool_spec.py`.

- [ ] Write failing tests proving a ToolSpec is frozen, serializes every canonical field, normalizes required scopes to a frozenset, and rejects an unknown effect through Pydantic validation.
- [ ] Run the focused test and observe missing-module RED.
- [ ] Implement frozen enums `ToolEffect` (`observe`, `workspace_write`, `execute`, `network_read`, `external_write`, `install`, `destructive`, `sensitive`), `IdempotencyKind` (`none`, `key`, `status_check`), and `ToolHealth` (`available`, `degraded`, `unavailable`). Implement frozen `ToolSpec` fields: `tool_id`, `description`, `input_schema`, `output_schema`, `effect`, `required_scopes`, `idempotency`, `timeout_seconds` (positive), `source`, `source_version`, and `health`.
- [ ] Export, verify focused tests and quality checks, and commit `feat: define canonical ToolSpec`.

### Task 3: Pure supervised Trust Policy

**Files:** Create `core/src/weatherflow/trust/{__init__.py,policy.py}` and `core/tests/trust/test_supervised_policy.py`.

- [ ] Write parameterized failing tests for the exact effect-to-decision table. Add tests proving a missing scope returns DENY before the effect rule, unavailable tools return HIDE, and `visible()` includes allow/sandbox/approve tools while excluding deny/hide tools.
- [ ] Run the focused test and observe missing-module RED.
- [ ] Implement frozen `DecisionKind(StrEnum)` values `allow`, `sandbox`, `approve`, `deny`, `hide`; frozen `PolicyDecision` fields `kind`, `reason`, `missing_scopes`; and `SupervisedPolicy.evaluate(tool, workspace)`. Evaluation order is health unavailable -> HIDE, missing required scopes -> DENY, then the locked effect table. `visible()` filters a sequence with the same evaluator and preserves input order.
- [ ] Run focused tests, then `make check` and `git diff --check`; commit `feat: add supervised Trust Policy`.

### Task 4: Document and audit P1c1

**Files:** Modify `AGENTS.md` and `README.md`.

- [ ] Add workspaces, capabilities, and trust to the file map; record that ToolSpec is descriptive and the pure policy must be repeated at execution time.
- [ ] Run locked sync, `make check`, `git diff --check`, and status review.
- [ ] Commit `docs: describe WeatherFlow Trust foundation`.

P1c1 ends here. P1c2 adds persistence, action proposals, and durable approvals; P1c3 freezes per-Run capability snapshots.
