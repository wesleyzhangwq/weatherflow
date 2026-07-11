# WeatherFlow v3 P1d3 Headless Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver a runnable headless daemon and CLI that create durable Runs, expose timelines/approvals/artifacts, and recover checkpoints from the same SQLite file after restart.

**Architecture:** `RuntimeContainer` is the one composition root for repositories, coordinators, catalog, model adapter, and loop. FastAPI and CLI are thin adapters. Workspace configuration becomes durable operational state. Background Run execution is tracked by the container but all recovery truth remains in SQLite.

**Tech Stack:** Python 3.12, FastAPI/httpx, argparse, asyncio, SQLite, pytest-asyncio.

---

## Locked contracts

- API/CLI never duplicate domain policy or state transitions.
- `client_request_id` retries return the same Run.
- Daemon restart reconstructs dependencies from disk and resumes serializable checkpoint state.
- WAITING_APPROVAL remains parked across restart.
- Local service binds loopback by default; remote exposure is not enabled here.

### Task 1: Durable Workspace repository and composition root

**Files:** Add migration 7; create workspace repository/tests; create `bootstrap.py` and tests.

- [ ] Persist versioned Workspace JSON with unique ID and create/get/list. Add a default Workspace bootstrap beneath `Settings.data_dir`.
- [ ] Implement `EchoModelAdapter` for deterministic local smoke operation and `RuntimeContainer.create(settings, model=None)` that initializes DB and wires every P1 repository/coordinator/loop dependency once.
- [ ] Test two containers over one data directory read the same Workspace, Runs, snapshots, checkpoints, and approvals; commit `feat: compose durable WeatherFlow runtime`.

### Task 2: Run/approval/artifact HTTP API

**Files:** Expand API schemas/app and integration tests.

- [ ] Add lifespan initialization and endpoints equivalent to `POST /v1/runs`, `GET /v1/runs/{id}`, cancel, timeline, `GET /v1/approvals`, approval decision, and artifact metadata/content. Run creation freezes the current capability surface and schedules the sole loop.
- [ ] Add typed 404/409 responses, idempotency tests, timeline order tests, approval park/decision tests, and no-Cockpit/desktop behavior assumptions at adapter boundary.
- [ ] Verify and commit `feat: expose durable Run HTTP API`.

### Task 3: CLI Run workflow and restart recovery

**Files:** Extend CLI and tests; add restart integration test.

- [ ] Add `weatherflow run <intent>`, `weatherflow status <run_id>`, `weatherflow timeline <run_id>`, and `weatherflow approve|deny <approval_id>`. JSON output is stable and machine-readable; `--data-dir` selects state.
- [ ] Test a Run interrupted after a persisted tool turn, destroy container, rebuild over same DB, resume without repeating the model turn, and finish. Test WAITING_APPROVAL remains parked after rebuild.
- [ ] Run CLI smoke commands and full checks; commit `feat: add recoverable WeatherFlow CLI Runs`.

### Task 4: P1 acceptance and documentation

- [ ] Document quick start and API/CLI examples. Add a P1 acceptance test proving create -> checkpoint -> approval -> decision -> execution/result -> SUCCEEDED with audit timeline.
- [ ] Run locked sync, `make check`, CLI/API smoke, diff/status checks; commit `docs: complete WeatherFlow v3 P1 headless core`.

P1 ends here. P2 adds the authenticated Tauri bridge, desktop surfaces, macOS metadata adapter, and Rhythm Intelligence.
