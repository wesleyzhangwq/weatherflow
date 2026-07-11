# WeatherFlow v3

WeatherFlow is a rhythm-aware personal agent OS. v3 is a clean-slate rewrite
with a local Python harness daemon and a macOS-first Tauri desktop shell.

P0 established the clean v3 package, health API, CLI, and quality gates. P1a
added the WAL-mode SQLite foundation and append-only Event Ledger. P1b now adds
durable Runs, idempotent creation, optimistic concurrency, deterministic
transitions, and atomic audit events through the sole Run Coordinator. P1c1
adds immutable Workspace authority boundaries, canonical ToolSpec descriptions,
and a fail-closed supervised Trust Policy. P1c2a adds durable, versioned Action
proposals and separate human Approval records with idempotency constraints.
P1c2b atomically persists side-effect proposals before parking Runs, resumes
after approve/deny without executing implicitly, and pauses expired approvals.
P1c3 resolves the smallest authorized tool surface and freezes canonical,
digest-addressed ToolSpecs per Run; catalog changes affect only new Runs.
P1d1 adds SHA-256 content-addressed artifacts with immutable manifests,
provenance events, physical deduplication, and rollback cleanup. The shared turn
loop begins with P1d2a provider-neutral model/tool protocols and optimistic,
durable Run checkpoints. P1d2b1 adds the sole shared loop: frozen-schema tool
visibility, checkpoint-before-dispatch, safe execution, atomic final commits,
and idempotent approval parking. P1d2b2 resumes approved actions exactly once
when possible; ambiguous execution failures and recovered EXECUTING actions
enter NEEDS_REVIEW without automatic retry.
P1d3 completes the headless core with one reconstructable RuntimeContainer,
durable Workspaces, local Run/approval/artifact HTTP APIs, machine-readable CLI
commands, and restart recovery from SQLite checkpoints.
P2a adds append-only deliberate/activity signals, six evidence-aware human-state
dimensions, silent RhythmPolicy, and backend-only weather projection. Ambient
metadata is limited to active/idle duration, switch counts, and coarse category
totals; raw screen, title, keystroke, clipboard, and audio content are rejected.

## Read first

- `weatherflow-architecture-v3.md`
- `docs/superpowers/specs/2026-07-12-weatherflow-v3-design.md`

WeatherFlow v2 is preserved in Git history and the local tag
`weatherflow-v2-final`; it is not a compatibility target.

## Requirements

- Python 3.12
- uv

## Quick start

```bash
cp .env.example .env
make install
make check
make dev
```

The daemon listens on `127.0.0.1:8765` by default.

```bash
curl http://127.0.0.1:8765/health
```

Expected response:

```json
{"status":"ok","service":"weatherflow-core","version":"3.0.0a1"}
```

Create and inspect a durable local Run:

```bash
weatherflow --data-dir ~/.local/share/weatherflow run "Explain this repository"
weatherflow --data-dir ~/.local/share/weatherflow status <run_id>
weatherflow --data-dir ~/.local/share/weatherflow timeline <run_id>
weatherflow --data-dir ~/.local/share/weatherflow approve <approval_id>
```

Equivalent HTTP entrypoints begin at `POST /v1/runs`, `GET /v1/runs/{run_id}`,
`GET /v1/runs/{run_id}/timeline`, and `GET /v1/approvals`.

## Current repository

```text
core/                    Python daemon package and tests
docs/superpowers/        Approved design and implementation plans
weatherflow-architecture-v3.md
```

Do not restore or copy v2 runtime modules into the v3 package.
