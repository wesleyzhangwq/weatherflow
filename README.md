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
Approval coordination, capability snapshots, Rhythm Intelligence, the desktop
shell, and Capability Packs follow.

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

## Current repository

```text
core/                    Python daemon package and tests
docs/superpowers/        Approved design and implementation plans
weatherflow-architecture-v3.md
```

Do not restore or copy v2 runtime modules into the v3 package.
