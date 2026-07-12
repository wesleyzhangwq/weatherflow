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
4. The floating companion is the primary habit surface.
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
8. Credentials never enter model-visible or durable diagnostic data.
9. Uncertain side effects enter NEEDS_REVIEW and are not blindly retried.
10. RhythmPolicy may change execution strategy but not the user's goal.
11. Low-confidence human state projects to mixed/unknown weather.
12. Semantic indexes are derived and rebuildable.
13. User deletion and retention policy outrank append-only audit storage.
14. Cockpit and system notifications never open from state changes alone.
15. No alternate execution path may bypass the Run Coordinator or Trust Plane.
16. Model adapters translate provider wire formats only; they cannot add tools,
    scopes, approvals, or durable provider-specific reasoning state.
17. Desktop Run submission acknowledges durable acceptance before model work;
    the daemon then owns background execution through the same shared turn loop.
18. A desktop Run always names an explicitly authorized Workspace. The default
    internal data directory is not a substitute for selecting a real project.
19. Activity sensing is disabled until the persisted onboarding preference
    explicitly enables it.

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
  Hidden reasoning is intentionally not persisted; Echo remains only as a
  visibly unconfigured smoke fallback.
- 2026-07-12: Promoted `MiniMax-M3` to the default production model. OpenAI-
  compatible requests disable M3 thinking so no hidden reasoning must be
  replayed or persisted. Local development standardizes on `pnpm dev:app`;
  debug Tauri supervises the reloadable Python source core, while release builds
  continue to supervise the bundled sidecar.
- 2026-07-12: Reset product delivery around one live loop before adding more
  integrations: authorize a real Workspace, acknowledge Capsule input quickly,
  execute MiniMax-M3 in the daemon background, reflect Run state through the
  Companion, and inspect results/approvals/artifacts in Cockpit. Provider and
  packaging expansion remains frozen until this loop passes a real read-only
  trajectory. Native activity sampling now requires persisted opt-in.
- 2026-07-12: Approved a bounded first-party integration surface limited to
  GitHub, Gmail, and Google Calendar. Connection is explicit and revocable;
  background fetch is read-only, silent, interval-bounded, and independently
  disableable per connector. Synced summaries are local derived context with
  source identifiers and timestamps. Connector credentials stay in Keychain and
  never enter prompts, logs, events, memory, or artifacts. Gmail is a narrow
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
