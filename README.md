# WeatherFlow v3

WeatherFlow is a local, rhythm-aware personal agent OS for macOS. The desktop
shell stays small and quiet; a Python daemon owns durable Runs, model turns,
capabilities, approvals, automation, connectors, memory, and recovery.

```text
Tauri Shell -> Python Harness Daemon -> Rhythm + Capability Packs -> Local Data
```

The current architecture is a clean v3 implementation. WeatherFlow v2 remains
available at Git tag `weatherflow-v2-final`, but it is not a compatibility
target.

## Read first

- `weatherflow-architecture-v3.md` — authoritative contracts and decision log
- `docs/superpowers/specs/2026-07-12-weatherflow-v3-design.md` — approved design
- `docs/release-checklist.md` — reproducible macOS release process
- `docs/flagship-trajectory.md` — deterministic end-to-end acceptance scenario
- `docs/first-party-capabilities.md`, `docs/extensions.md`, and `docs/mcp.md` —
  capability boundaries

## Core boundaries

- ActivityWatch is the only raw activity fact source and runs independently.
  WeatherFlow reads it through the loopback REST API, uses only a short-lived
  read-only SQLite fallback for bounded diagnostics or historical analysis, and
  never writes raw activity into its own database.
- Activity titles, URLs, application names, connector content, and model output
  are untrusted data. They never become instructions or execution authority.
- WeatherFlow stores only derived activity task/revision/statistics metadata and
  reproducible evidence references. Fixed summary windows use `Asia/Shanghai`
  boundaries and are recovered idempotently after restarts.
- Human weather and Agent task state remain separate. Rhythm policy changes
  execution strategy, not the user's goal.
- Capabilities describe what exists; Trust Policy decides what may execute.
  External writes, installs, and destructive actions require durable approval.
- Broker-managed provider tokens never enter WeatherFlow. The Composio project
  credential is stored in macOS Keychain; connected accounts remain broker-owned.

## Requirements

- macOS 13 or newer on Apple Silicon
- Python 3.12 and `uv`
- Node.js 22+, pnpm 10, and Rust stable
- A locally running ActivityWatch installation for Watch data

## Develop

```bash
make install
make check
pnpm dev:signing:setup   # once per Mac when no local development signer exists
pnpm model:configure:cn  # optional MiniMax configuration; prompts without echo
pnpm dev:app
```

`pnpm dev:app` launches the current source tree: Vite, the Tauri shell, and the
Python daemon. It does not open a stale release bundle or reuse the last
PyInstaller application. The daemon listens on `127.0.0.1:8765` by default.

Useful focused commands:

```bash
make test           # Python tests, excluding dedicated eval/security gates
make eval           # deterministic flagship trajectory
make security-check
make desktop-check
make rust-check
make clean          # reproducible caches and build output only
pnpm dev:web
pnpm model:status
```

## Release

```bash
make release-app    # assemble the current local macOS release
make run-release    # verify and launch the assembled WeatherFlow.app
make release-check  # full quality, sidecar, checksum, signing, and DMG gates
```

The canonical local application is `release/macos/WeatherFlow.app`. Large
application and DMG products are reproducible and ignored; checksums, SBOM,
license inventory, release status, and signing blocker records remain tracked.

## Repository map

```text
core/src/weatherflow/   Python business core and restart boundary
core/tests/             unit, contract, integration, security, and eval gates
desktop/src/            Companion, Capsule, Cockpit, Watch, and typed bridge
desktop/src-tauri/      thin native shell and sidecar supervisor
extensions/             verified extension packages
tools/dev/              current-source development launch tooling
tools/release/          reproducible macOS release tooling
docs/                   current operating and capability documentation
```

Run `make check` before committing. Do not restore v2 runtime modules or add a
second workflow, policy, activity collection, or model loop.
