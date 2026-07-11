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
- Uncertain side effects enter NEEDS_REVIEW, not automatic retry.
- User deletion outranks append-only retention.
- No v2 compatibility or fallback path.

## Current file map

```text
core/
  src/weatherflow/
    api/             HTTP adapter
    artifacts/       content-addressed blobs and immutable provenance
    capabilities/    ToolSpec catalog, resolver, immutable Run snapshots
    events/          immutable Event envelope and append-only ledger
    runs/            Run model, optimistic repository, sole state coordinator
    runtime/         provider-neutral turns and serializable Run checkpoints
    storage/         SQLite connection and numbered migrations
    trust/           policy plus separate durable Action/Approval state
    workspaces/      action roots, scopes, budgets, and policy boundary
    bootstrap.py     sole dependency composition root and restart boundary
  tests/             unit, contract, and integration tests
docs/superpowers/    approved specifications and implementation plans
weatherflow-architecture-v3.md
```

Add new top-level areas only when the approved phase plan calls for them.

## Required loop

```bash
make lint
make format-check
make test
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
- Persist side-effect Actions before Approval; never treat approval as execution.
- Use ApprovalCoordinator to park/decide/resume; expiry cancels Action and pauses Run.
- Do not create a second agent loop, workflow engine, or policy path.
- Do not push, publish, merge, or create releases without explicit instruction.
