# WeatherFlow OS Sandbox and Lightweight Agent Core Plan

- **Date:** 2026-07-15
- **Status:** Implemented foundation; native release launcher remains gated
- **Authority:** `weatherflow-architecture-v3.md` and the approved v3 design
- **Reference:** `earendil-works/pi@dcfe36c79702ec240b146c45f167ab75ecddd205`,
  `packages/agent`

## Outcome

WeatherFlow can execute authorized project scripts, builds, and tests inside a
real macOS OS sandbox, while its Agent Core remains one small provider-neutral
turn loop with typed tools and lifecycle events. Durable Runs, frozen routes,
Trust, Actions, Approvals, recovery, RhythmPolicy, and artifacts remain explicit
WeatherFlow owners around that loop.

## Why these are one program

The core decides *what* tool call advances a turn. Trust decides *whether* the
call is allowed. The sandbox decides *where and under which kernel restrictions*
the process runs. Treating sandboxing as a command helper would preserve the
current oversized loop and make future cancellation, streaming, steering, and
recovery inconsistent.

```text
SharedTurnLoop
  -> ordered typed turn
  -> ToolDispatcher / Trust decision
  -> durable Action barrier
  -> SandboxBackend
  -> validated Observation
  -> checkpoint and next turn
```

## Reference lessons from pi-agent-core

Adopt:

- one low-level provider-neutral loop;
- a small state wrapper rather than a workflow graph;
- ordered lifecycle events for agent, turn, message, and tool execution;
- validated preflight before tools and a post-execution normalization barrier;
- ordered multi-tool results even when safe reads run concurrently;
- explicit abort, steering, follow-up, and context transformation seams.

Do not adopt as WeatherFlow authority:

- mutable process-local state as the source of truth;
- provider call IDs as durable Action identities;
- direct tool execution without the Trust/Action boundary;
- non-durable queues or events as crash recovery state;
- a second loop for Workers, Automations, CLI, MCP, or desktop requests.

## Delivery sequence

### Progress on 2026-07-15

- S1 and S2 are implemented. The repository's complete `make check` now runs
  through `DeveloperExecutor -> MacOSSeatbeltSandbox` with return code 0.
- The sandboxed proof covered 493 Python tests, the eval and hardening suites,
  51 desktop tests plus the production Vite build, and 18 Rust tests plus
  `cargo check`. Host-side Seatbelt integration tests separately exercise the
  non-nestable escape probes.
- C1 is implemented with a provider-neutral `AgentCore.next_turn`, a
  `TurnCommitter` checkpoint/event barrier, and a `ToolDispatcher` that owns the
  Trust/Action/Approval/execution/Observation path. `SharedTurnLoop` remains the
  sole coordinator and is reduced from 1,129 to 659 lines after control wiring.
- The first C2 slice is implemented with a durable SQLite `run_controls` queue.
  Steering is atomically injected before the next model request; follow-up is
  atomically selected instead of final-result commit. Focused runtime and API
  tests prove ordered application, restart-safe non-replay, and terminal-state
  rejection. Bounded compaction and richer streaming projections remain.
- S3 now covers managed MCP process entrypoints: fixed-version npm installation
  uses an approved HTTPS-only sandbox, and long-lived filesystem stdio runs
  offline/read-only through `spawn_stdio`. Missing sandbox support fails closed;
  Playwright is unavailable until a redirect-safe egress broker exists.
- Startup now caches a real escape-denial probe, descendants cannot create a new
  session/process group, and the fixed resource launcher removes Python
  `preexec_fn` without interpolating project argv. The deprecated
  `/usr/bin/sandbox-exec` entrypoint still requires a native release replacement.
- AgentCore emits value-free model start/retry/completion/failure lifecycle
  projections. Durable turn and tool events remain ordered behind their commit
  barriers; bounded transcript compaction remains a later C2 slice.
- Final host acceptance passed with 522 Python tests, 1 eval, 4 hardening
  tests, 51 desktop tests plus production build, and 18 Rust tests plus
  `cargo check`. The same repository `make check` then completed through
  `DeveloperExecutor -> MacOSSeatbeltSandbox` in loopback-only mode with return
  code 0 in 200,219 ms: 509 Python tests passed and 13 non-nestable Seatbelt
  probes skipped, followed by the same eval, hardening, desktop, and Rust gates.

### S1 — Typed sandbox and macOS backend

- Add `weatherflow.sandbox` request/result/limits contracts and backend protocol.
- Implement a default-deny macOS Seatbelt backend with runtime availability
  probing and no subprocess fallback.
- Enforce scoped roots, isolated HOME/temp, bounded environment, offline
  networking, CPU/wall/file/fd/output limits, and process-group
  cleanup.
- Permit only explicit loopback IP traffic and Unix sockets rooted in the
  private HOME or authorized writable roots. Processes may signal their own
  children but not host processes.
- Reuse only reviewed read-only Cargo registry/Git caches through a private
  offline `CARGO_HOME`; never expose Cargo credentials or config.
- Prove filesystem, network, Keychain, environment, signal, timeout, and child
  process confinement with macOS integration tests.

### S2 — Developer Pack build/test activation

- Replace the version-only subprocess path with `SandboxBackend` requests.
- Admit direct executable Workspace scripts plus reviewed `make`, `uv run`,
  Python test scripts/modules, npm/pnpm scripts, and Cargo build/test frontends.
- Continue denying package installation, shell strings, Git remote mutation,
  unknown PATH entries, and protected-root overlap.
- Run WeatherFlow's own narrow Python, desktop, and Rust checks through the
  sandbox, then run `make check` through it as the end-to-end proof.

### S3 — Sandbox runtime coverage and native hardening

- Replace the deprecated `sandbox-exec`/`preexec_fn` launch path with a small
  native runner before release, preserving the typed `SandboxBackend` contract.
- Add a startup escape-denial health probe and descendant tracking that cannot
  be evaded by a child creating a new process group/session.
- Route installed stdio MCP servers and approved package-installer subprocesses
  through dedicated least-privilege sandbox profiles. Their network and internal
  package roots are not equivalent to a Developer Workspace execution request.
- Keep unavailable or unhealthy backends fail-closed; never widen S1/S2 profiles
  as a compatibility shortcut.

### C1 — Thin turn engine

- Extract immutable turn input/output and lifecycle event types from
  `SharedTurnLoop` without changing state ownership.
- Extract deterministic model-turn preparation, tool dispatch, and turn commit
  seams; keep `SharedTurnLoop` as the sole coordinator.
- Make checkpoints the barrier before dispatch and events projections of
  committed facts, never an alternate state store.

### C2 — Control and context

- Add durable steering/follow-up inputs at turn boundaries.
- Add bounded context transformation/compaction with source references.
- Add streaming lifecycle projections while preserving checkpoint ordering and
  provider-continuation isolation.

### C3 — Composition and acceptance

- Split `RuntimeContainer.create` into typed composition groups without adding
  another runtime path.
- Prove Orchestrator/Worker parity, cancellation, approval resume, recovery,
  model switching, ordered batches, cost budgets, and sandboxed build/test in
  deterministic trajectories.

## Completion evidence

- No capability executor launches project commands outside `SandboxBackend`.
- Escape tests prove denial rather than merely checking generated profiles.
- A real authorized Workspace script, Python test, frontend build/test, Rust
  check, and repository `make check` complete through the OS sandbox.
- Sandbox absence makes execution unavailable and never falls back.
- `SharedTurnLoop` remains the only model loop and is materially smaller; all
  extracted components have narrow typed contracts and focused tests.
- `make check` and the macOS sandbox integration suite pass from a clean state.
