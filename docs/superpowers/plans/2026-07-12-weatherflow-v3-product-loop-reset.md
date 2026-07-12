# WeatherFlow v3 Product Loop Reset Plan

**Goal:** Turn the verified runtime skeleton into one real daily-use loop:
authorize a project, submit through Capsule, execute MiniMax-M3 in the
background, reflect progress through Companion, and inspect/continue the result
through Cockpit.

## Scope lock

- [x] Keep Calendar, GitHub, Research, MCP discovery, extension marketplace,
  release packaging, and advanced memory automation frozen during this reset.
- [x] Preserve the sole `RuntimeContainer -> SharedTurnLoop -> Trust Plane`
  execution path; background scheduling is an adapter over that path, not a
  second runtime.
- [x] Use the Developer Pack only for the first live trajectory.

## P5a: Workspace authorization

- [x] Add typed create/list/get Workspace APIs. Creating a Workspace requires
  an existing local directory and explicit user action; default grants are the
  bounded Developer read/write/execute scopes.
- [x] Add a native macOS directory picker and Cockpit Workspace selector.
  Persist the selected Workspace ID in local desktop preferences and attach it
  to Run, rhythm, status, and snapshot requests.
- [x] Add `pnpm` to the no-shell Developer command allowlist.

## P5b: Background Run lifecycle

- [x] Make `POST /v1/runs` acknowledge after durable creation/snapshot freeze,
  then schedule the existing `resume_run()` path in a daemon-owned background
  manager.
- [x] Deduplicate tasks per Run, retain task exceptions as durable failure or
  pause state, and never report success before the shared loop commits it.
- [x] On daemon startup, resume only safe queued/planning/running/paused Runs;
  keep waiting-approval and needs-review Runs parked.
- [x] Prove Capsule acknowledgement excludes model latency and the real desktop
  path no longer leaves an unowned queued Run.

## P5c: Usable Cockpit result loop

- [x] Add recent Run listing and cancellation; select a Run rather than showing
  only the latest record.
- [x] Show final result, user-readable execution summaries, approvals, and
  artifacts for the selected Run.
- [x] Fetch artifact bytes through the authenticated bridge instead of a broken
  relative frontend URL.
- [x] Add a follow-up input that creates a new idempotent Run linked to the
  selected result context without introducing a chat-specific execution path.

## P5d: Rhythm consent and correction

- [x] Gate native activity sampling on the persisted onboarding sensor choice.
- [x] Add deliberate check-in and correction controls for the selected
  Workspace; correction remains append-only.
- [x] Surface sensor unavailable/disabled state without inventing a precise
  weather scene.

## P5e: Real acceptance

- [x] Replace component-mock acceptance for this loop with an integration test
  that uses the real HTTP bridge, background manager, SQLite state, and a
  scripted adapter.
- [x] Run a user-authorized, read-only MiniMax-M3 trajectory against the real
  WeatherFlow Workspace: inspect repository state and return three prioritized
  issues without modifying files.
- [x] Verify no external write, no project mutation, a terminal Run, visible
  result/timeline, and zero orphaned background processes.
- [x] Run `make check`, debug and release Rust checks, and keep the worktree
  clean. Do not rebuild or publish release artifacts in this phase.

## Acceptance evidence

- Real HTTP integration: authenticated loopback bridge, SQLite, authorized
  project, daemon-owned background task, terminal result, timeline, and zero
  orphaned tasks.
- Real MiniMax-M3 read-only Run `01KXA8CSYR02AR33TEN8GDM4B8`: two
  `developer.read_file` calls plus one `developer.git_status`, terminal
  `succeeded`, zero artifacts, and an unchanged project diff.
- The preceding live Run exposed one follow-up risk: MiniMax-M3 can omit a
  required tool argument and stop early. This remains observable in the Run
  timeline and is a model/tool-use quality concern, not a second execution
  path or hidden write.
- Final gates: 239 core tests, 1 eval, 4 hardening tests, 12 desktop tests,
  frontend production build, 6 Rust tests, debug `cargo check`, release
  `cargo check`, and `git diff --check`.
