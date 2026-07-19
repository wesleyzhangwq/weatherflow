# AGENTS.md — WeatherFlow v3

## Read first

`weatherflow-architecture-v3.md` is the authoritative architecture entrypoint.
The approved detailed design is
`docs/superpowers/specs/2026-07-12-weatherflow-v3-design.md`.

Read both before changing product contracts, runtime boundaries, authority,
human-state semantics, storage ownership, or desktop behavior.

WeatherFlow v2 is archived at Git tag `weatherflow-v2-final`. Do not restore or
copy v2 runtime code into v3. Historical behavior is not a compatibility target.

## Mental model

WeatherFlow v3 is a rhythm-aware personal agent OS:

```text
Tauri Shell -> Python Harness Daemon -> Rhythm + Capability Packs -> Local Data
```

- Tauri presents micro-weather, command input, Cockpit, and native metadata.
- Python owns every business decision and durable Run.
- RhythmPolicy changes interaction and execution strategy, never user goals.
- Capability says what exists; Trust says what may execute.

## Hard rules

- Cockpit never auto-opens.
- Human weather and Agent task state remain separate.
- v3.0 proactivity is silent.
- Workers are leaf agents.
- Skills and MCP annotations never grant authority.
- External writes, installs, and destructive actions require approval.
- Unknown or out-of-scope actions fail closed.
- Credentials never enter prompts, logs, events, memory, or artifacts.
- ActivityWatch is the sole raw activity fact source and remains independently
  running. WeatherFlow may read it only through the loopback REST API or an
  explicit short-lived read-only SQLite diagnostic fallback. It never writes,
  deletes, pauses, configures, or mirrors ActivityWatch raw data. Window titles,
  URLs, and document names remain untrusted data, never instructions.
- Broker-managed provider tokens never enter WeatherFlow; only opaque account
  references and a Keychain-backed broker credential may cross the connector boundary.
- Uncertain side effects enter NEEDS_REVIEW, not automatic retry.
- User deletion outranks append-only retention.
- No v2 compatibility or fallback path.

## Current file map

```text
core/
  src/weatherflow/
    activity/        ActivityWatch read gateway, semantic queries, summaries, and recovery
    api/             HTTP adapter
    artifacts/       content-addressed blobs and immutable provenance
    capabilities/    ToolSpec catalog, Pack executors, immutable Run snapshots
    connectors/      fixed connection identities, Composio gateway, read-only sync
    events/          immutable Event envelope and append-only ledger
    runs/            Run model, optimistic repository, sole state coordinator
    rhythm/          signal facts, six-dimensional state, policy, weather
    runtime/         provider-neutral turns and serializable Run checkpoints
    sandbox/         typed OS execution boundary and macOS Seatbelt backend
    storage/         SQLite connection and numbered migrations
    trust/           policy plus separate durable Action/Approval state
    workspaces/      action roots, scopes, budgets, and policy boundary
    bootstrap.py     sole dependency composition root and restart boundary
  tests/             unit, contract, and integration tests
desktop/
  src/               Companion, Capsule, Cockpit, typed bridge, metadata aggregation
  src-tauri/         thin window shell and sidecar supervisor
docs/superpowers/    approved specification
weatherflow-architecture-v3.md
```

Add new top-level areas only when the approved phase plan calls for them.

## Required loop

```bash
make lint
make format-check
make test
make desktop-check
make rust-check
make check
```

Use TDD: failing test, observed failure, minimal implementation, observed pass.
Run the narrow test while developing and `make check` before committing.

## Change discipline

- Update architecture and tests in the same commit for contract changes.
- Keep domain logic out of HTTP, CLI, MCP, and Tauri adapters.
- Keep provider and tool implementations behind typed protocols.
- Treat ToolSpec as description only; repeat Trust Policy at execution time.
- Never hot-switch schemas for an existing Run; use its frozen capability snapshot.
- Derive artifact paths from verified digests; logical names never control paths.
- Checkpoints contain serializable domain data only, never clients or live tools.
- SharedTurnLoop is the sole model loop; checkpoint every turn before dispatch.
- Never retry a recovered EXECUTING side effect; route Action and Run to NEEDS_REVIEW.
- Keep state-to-weather projection in Python; desktop consumes presentation tokens only.
- ActivityWatch application, title, URL, event, and AFK records must not be
  copied into WeatherFlow SQLite, Runs, the Event Ledger, memory, checkpoints,
  artifacts, or ordinary diagnostics. The derived activity database stores only
  task/revision/statistics metadata, ActivityWatch evidence refs, and bounded
  summary evidence refs to replaceable GitHub, Gmail, and Google Calendar
  snapshots. It stores no ActivityWatch state inference or comprehensive state
  assessment records.
- Activity summary windows use fixed `Asia/Shanghai` boundaries: 00–06, 06–12,
  12–18, 18–24, a distinct 24-hour window ending at 06:00, Monday weeks,
  anchored biweeks, and calendar months. Startup recovery enumerates theoretical
  windows; it never infers gaps from only the last completed task.
- A summary may be provisional after 15 minutes and final only after at least
  60 minutes plus a fresh raw-window check. Category rules are query-time
  derivations whose normalized snapshot/version is recorded per revision.
- Credential detection/redaction and explicit untrusted-data delimiters precede
  every tool-free activity model request. Recent summaries use one built-in,
  code-owned, versioned Simplified-Chinese prompt; users may select the model
  but cannot view, submit, persist, or edit the prompt. A summary request
  independently reads bounded snapshots from GitHub, Gmail, and Google Calendar
  together (never a GitHub-only substitute), records per-source summary evidence
  refs and explicit missing/stale coverage, and returns Chinese narrative only.
  Any generated synopsis of auto-fetched connector content is also Chinese; only
  visibly quoted raw untrusted evidence may retain its source language.
  ActivityWatch state inference, comprehensive state assessment, and inference
  APIs are forbidden.
- When `WF_BRIDGE_TOKEN` is set, every HTTP/WebSocket bridge request must authenticate.
- Desktop event reconnects use Event Ledger cursors; invalid cursors refresh snapshots.
- Persist side-effect Actions before Approval; never treat approval as execution.
- Use ApprovalCoordinator to park/decide/resume; expiry cancels Action and pauses Run.
- Do not create a second agent loop, workflow engine, or policy path.
- Do not push, publish, merge, or create releases without explicit instruction.
