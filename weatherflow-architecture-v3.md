# WeatherFlow Architecture v3

## 0. Authority

This document is the authoritative architecture entrypoint for WeatherFlow v3.
The approved detailed specification is
`docs/superpowers/specs/2026-07-12-weatherflow-v3-design.md`.

If the two documents conflict, this file is the conflict resolver. A contract
change must update both documents in one commit and append a decision entry to
this file before runtime code changes.

WeatherFlow v2 is archived at the local Git tag `weatherflow-v2-final`. v3 has
no code, API, or data compatibility obligation to v2.

## 1. Product constitution

1. WeatherFlow is a rhythm-aware personal agent OS.
2. Human state is a runtime input, not merely a label or animation.
3. Explicit user goals outrank rhythm-derived strategy recommendations.
4. The floating weather glyph is the primary habit surface.
5. Human weather and Agent work state use separate visual channels.
6. The command capsule is pure input; the Cockpit never auto-opens.
7. v3.0 proactivity is silent ambient presentation only.
8. Python Harness Daemon is the sole business core.
9. Tauri owns presentation and native OS bridging only.
10. Capability and authority are separate systems.
11. User data is local, inspectable, exportable, and deletable.
12. macOS is the only supported v3.0 desktop platform.
13. The Cockpit's primary workspace is conversation; Runs, rhythm, approvals,
    integrations, and settings support that conversation instead of competing
    with it as an equal card grid.

## 2. System model

```text
Tauri Desktop Shell
  -> authenticated local HTTP/WebSocket
Python Harness Daemon
  -> Run Coordinator + Agent Runtime + Capability Plane + Trust Plane
  -> Rhythm Intelligence
  -> Capability Packs
  -> Operational SQLite + Event Ledger + Memory + Artifact Store
```

The daemon is also usable through CLI and MCP. No client owns business state.

## 3. Hard contracts

1. Every command creates an idempotent Run.
2. Run status changes only through the deterministic Run Coordinator.
3. Workers are leaf agents and cannot spawn more agents.
4. Tool visibility is frozen per Run and checked again at execution.
5. Skills and MCP annotations never grant authority.
6. External writes, installs, and destructive actions require approval.
7. Unknown, unhealthy, or out-of-scope capabilities fail closed.
8. Credentials never enter model-visible or durable diagnostic data. A provider
   token may be held by an explicitly approved connection broker; WeatherFlow
   stores only a Keychain-backed broker credential and opaque account references.
9. Uncertain side effects enter NEEDS_REVIEW and are not blindly retried.
10. RhythmPolicy may change execution strategy but not the user's goal.
11. Low-confidence human state projects to mixed/unknown weather.
12. Semantic indexes are derived and rebuildable.
13. User deletion and retention policy outrank append-only audit storage.
14. Cockpit and system notifications never open from state changes alone.
15. No alternate execution path may bypass the Run Coordinator or Trust Plane.
16. Model adapters translate provider wire formats only; they cannot add tools,
    scopes, approvals, or write durable state. An adapter may return one opaque
    provider-continuation envelope to the SharedTurnLoop, which is the only
    component allowed to persist it through the typed continuation store.
17. Desktop Run submission acknowledges durable acceptance before model work;
    the daemon then owns background execution through the same shared turn loop.
18. A desktop Run always names an explicitly authorized Workspace. The default
    internal data directory is not a substitute for selecting a real project.
19. Activity sensing is disabled until the persisted onboarding preference
    explicitly enables it.
20. Desktop credential mutation belongs to Tauri's native OS bridge. Renderer
    code may set, delete, or inspect presence for a fixed provider, but can never
    read a stored secret. Python may only resolve a fixed provider through the
    private native bridge at the transport boundary.
21. Provider continuations are protocol recovery data, never user memory. They
    are encrypted at rest with an installation key held in Keychain, scoped to a
    Run and model, excluded from prompts/logs/events/checkpoints/memory/artifacts,
    deleted when the Run becomes terminal, and expire after seven days otherwise.
22. Provider/model selection is frozen per Run at durable acceptance. Workspace
    configuration is only the default for future Runs; SharedTurnLoop resolves
    the immutable Run route and never reads or mutates one process-global adapter.

## 4. v3.0 scope

v3.0 includes the Python daemon, Tauri three-surface desktop, durable harness,
Rhythm Intelligence, risk-based supervised autonomy, Developer/Research/
Personal Operations capability packs, Skills, MCP, Agent Definitions, local
ownership, diagnostics, and macOS packaging.

v3.0 excludes Windows/Linux support, mobile/cloud/team features, content-level
desktop monitoring, recursive agent networks, a workflow canvas, broad email or
messaging catalogs beyond the bounded first-party Gmail connector, and all v2
compatibility.

## 5. Change discipline

1. Read this document and the approved detailed specification before edits.
2. Write a failing contract or behavior test before implementation.
3. Keep modules single-purpose and communicate through typed interfaces.
4. Run `make check` before every commit.
5. Contract changes update architecture and tests in the same commit.
6. Never push, publish, or merge without explicit user instruction.

## 6. Decision record

- 2026-07-12: Approved clean-slate v3 rewrite with Python core, Tauri shell,
  macOS-first delivery, no v2 compatibility, and a rhythm-aware general harness.
- 2026-07-12: Approved MiniMax as the first production ModelAdapter. Per-Workspace
  configuration stores model/base URL plus a credential reference in SQLite;
  the API key lives only in macOS Keychain and enters requests at the transport
  boundary. Provider-safe function aliases map back to the frozen ToolSpec IDs.
  Provider reasoning is excluded from domain state; Echo remains only as a
  visibly unconfigured smoke fallback.
- 2026-07-13: Replaced direct desktop Python Keychain access with a narrow native
  Tauri credential boundary. Renderer commands are limited to `set`, `delete`,
  and `status`; the Python daemon receives only `resolve` over a `0600` Unix
  Domain Socket. Each Tauri launch creates a random 256-bit token and hands the
  socket bootstrap to the daemon through stdin, never environment or disk.
  Providers are a fixed enum; arbitrary service/account names fail closed.
  CLI-only use may retain its own Keychain adapter outside this desktop path.
- 2026-07-12: Promoted `MiniMax-M3` to the default production model. OpenAI-
  compatible requests disable M3 thinking so no hidden reasoning must be
  replayed or persisted. Local development standardizes on `pnpm dev:app`;
  the development launcher owns process cleanup and Tauri owns exactly one
  authenticated Python child. Secure stdin bootstrap deliberately disables
  Uvicorn subprocess reload; Vite remains live for renderer edits, while Python
  edits require a daemon/app restart. Release builds continue to load bundled
  assets and supervise the bundled sidecar. Event Ledger clients reconnect from
  their last cursor after a daemon restart.
- 2026-07-12: Reset product delivery around one live loop before adding more
  integrations: authorize a real Workspace, acknowledge Capsule input quickly,
  execute MiniMax-M3 in the daemon background, reflect Run state through the
  Companion, and inspect results/approvals/artifacts in Cockpit. Provider and
  packaging expansion remains frozen until this loop passes a real read-only
  trajectory. Native activity sampling now requires persisted opt-in.
- 2026-07-12: Approved a bounded integration surface limited to
  GitHub, Gmail, and Google Calendar. Connection is explicit and revocable;
  background fetch is read-only, silent, interval-bounded, and independently
  disableable per connector. Synced summaries are local derived context with
  source identifiers and timestamps. WeatherFlow-held connector credentials
  stay in Keychain and never enter prompts, logs, events, memory, or artifacts.
  Gmail is a narrow
  exception to the earlier email deferral; broader email and messaging remain
  out of scope.
- 2026-07-12: Approved a conversation-first Chinese desktop redesign grounded
  in the local OpenHuman/harness interaction model: persistent left navigation,
  conversation as the dominant workspace, and secondary dedicated views for
  Runs, rhythm, integrations, and settings. The floating Companion remains the
  primary habit surface and Cockpit remains explicit-only.
- 2026-07-12: Expanded the production model SPI from MiniMax-only to a curated
  set of mainland-China OpenAI-compatible providers: MiniMax, DeepSeek,
  Moonshot/Kimi, Alibaba Model Studio/Qwen, Zhipu GLM, SiliconFlow, and StepFun.
  Provider presets expose model and HTTPS API endpoint to the user, while API
  keys remain in Keychain. A custom compatible endpoint may be entered but
  cannot change capability or Trust policy. MiniMax-specific thinking handling
  remains an adapter quirk, not a runtime contract.
- 2026-07-13: Deferred automatic model routing. Each provider credential is
  configured once and may expose multiple maintained language models; exactly
  one provider/model pair is active per Workspace and the user may switch it
  from the conversation composer or Settings. First-party catalogs intersect
  the official maintained allowlist with the credential-scoped `/models`
  response; SiliconFlow uses its live text-model catalog. The primary desktop
  flow uses fixed official endpoints and never reads a key back into React.
  Models that require hidden reasoning replay remain visible and are selectable
  only when the encrypted continuation store is available.
- 2026-07-13: Approved durable MiniMax M2.x continuity through an independent
  encrypted `provider_continuations` store. The SharedTurnLoop persists the
  complete provider assistant message for tool/delegation turns with AES-256-GCM
  and authenticated Run/provider/model/step metadata. The installation key is
  generated by the native shell and held in Keychain; it is not renderer-
  addressable. Records are deleted on terminal Run state and otherwise expire
  after seven days. Decryption failure, missing required history, expiry, or a
  provider/model mismatch fails closed to `NEEDS_REVIEW`. Raw continuation data
  never becomes a timeline entry, diagnostic, event, checkpoint, memory, profile
  assertion, artifact, or human-state signal.
- 2026-07-13: Corrected model ownership from a mutable process-global adapter to
  immutable `run_model_routes`. A Workspace selection is copied into the Run at
  acceptance, Worker Runs inherit their parent route, and later model switches
  affect only later Runs. Each route emits a credential-free
  `model.route_bound` event. Provider/model identity is supplied to the model as
  trusted runtime metadata so conversational self-identification does not rely
  on pretrained claims.
- 2026-07-12: Simplified the ambient shell from a character/orb into one native
  weather icon. The entire icon is a click-or-drag target: movement beyond a
  small threshold starts native window dragging, while a click opens the pure
  input Capsule. Agent state is limited to a small secondary status dot. The
  Capsule closes on submit, Escape, explicit close, or loss of window focus.
- 2026-07-13: Approved Composio Direct/BYO-key as the v3 connection broker for
  the fixed GitHub, Gmail, and Google Calendar surface. The user's scoped
  Composio project key lives only in macOS Keychain; Composio owns provider
  access/refresh tokens, while WeatherFlow persists opaque connected-account
  references, per-Workspace read scopes, and bounded derived snapshots. A first
  connection may create a Composio-managed Auth Config
  restricted to WeatherFlow's fixed read actions; this is broker setup, not a
  grant of Agent authority. The scoped key therefore needs Auth Config read/write,
  Connected Account read/write, and Tool Execution write, with all other Composio
  permission areas disabled. Managed OAuth uses v3 Connect Link only; no legacy
  initiate/v1/v2 fallback, generic
  Composio model tool, Trigger lifecycle, WeatherFlow account login, or cloud
  backend is introduced. Connection never grants execution authority.
- 2026-07-13: Standardized macOS development on a stable local code-signing
  requirement. `pnpm dev:app` signs Cargo's final debug executable immediately
  before launch with the fixed identifier `ai.weatherflow.desktop.dev` and a
  fixed local certificate; ad-hoc/linker signatures are not accepted. The
  one-time setup certificate is development-only and does not replace release
  Developer ID signing or notarization. This keeps Keychain/TCC authorization
  stable across rebuilds without changing credential ownership or exposing
  secret material.
