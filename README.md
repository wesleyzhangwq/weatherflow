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
P2b adds optional per-launch bearer authentication (`WF_BRIDGE_TOKEN`) and an
ordered `WS /v1/events?cursor=` stream. Invalid cursors explicitly require a
fresh desktop snapshot instead of silently losing state.
P2c/P2d add the tested Companion, pure-input Capsule, explicit Cockpit, thin
Tauri window shell, authenticated sidecar supervision, bounded daemon recovery,
reduced-motion UI, and privacy-safe macOS activity aggregation.
P3a adds first-party Developer, Research, Calendar, and GitHub release
capabilities. Workspace-installed Packs and granted scopes define the smallest
per-Run frozen tool surface; unavailable providers are hidden, local mutations
remain root-bounded, and external mutations execute only through durable
approval Actions.
P3b adds durable leaf Worker delegation through the same shared turn loop.
Worker child Runs inherit only a filtered subset of the parent's frozen
capabilities, high-risk approval effects are excluded, concurrency is capped at
three, and the parent receives only a compact result plus Artifact references.
P3c binds immutable Rhythm strategy to Runs and validates the complete
overloaded-release story with deterministic trajectory, integrated desktop,
and native macOS shell gates.

## Read first

- `weatherflow-architecture-v3.md`
- `docs/superpowers/specs/2026-07-12-weatherflow-v3-design.md`
- `docs/first-party-capabilities.md`
- `docs/worker-delegation.md`
- `docs/flagship-trajectory.md`
- `docs/extensions.md`
- `docs/mcp.md`

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
make eval
make dev
```

Desktop development uses the same root gate:

```bash
cd desktop && npm ci
make check
cd desktop && npx tauri dev
```

The development sidecar shim expects the `weatherflow` CLI on `PATH`; P4
packaging replaces it with a standalone Python sidecar binary.

P2 native acceptance also runs successfully with:

```bash
cd desktop
npx tauri build --debug --no-bundle
```

Release `.app`/`.dmg` assembly, signing, and notarization remain P4 concerns.

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
weatherflow --data-dir ~/.local/share/weatherflow mcp-server
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
