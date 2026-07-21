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
11. User data is local-first, inspectable, exportable, and deletable. Consented
    ActivityWatch-level activity metadata may leave the device only through the
    audited remote-summary boundary described below.
12. macOS is the only supported v3.0 desktop platform.
13. The Cockpit's primary workspace is conversation; Runs, unified Watch,
    approvals, integrations, and settings support that conversation instead of
    competing with it as an equal card grid. Watch owns detailed observed
    activity presentation; there is no standalone rhythm/status-weather
    destination.

## 2. System model

```text
Tauri Desktop Shell
  -> authenticated local HTTP/WebSocket
Python Harness Daemon
  -> Run Coordinator + Agent Runtime + Capability Plane + Trust Plane
  -> Rhythm Intelligence
  -> Capability Packs
  -> ActivityWatch Read Gateway
  -> Operational SQLite + Event Ledger + Activity Summary Ledger + Memory + Artifact Store
```

The daemon is also usable through CLI and MCP. No client owns business state.

## 3. Hard contracts

1. Every command creates an idempotent Run. A `client_request_id` is bound to
   its original Workspace and conversation session and cannot return a Run
   across either boundary.
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
19. ActivityWatch is the sole raw activity fact source and runs independently of
    WeatherFlow. WeatherFlow never starts, stops, configures, pauses, deletes
    from, or writes buckets/events/settings in ActivityWatch. Remote model
    analysis remains separately configured and receives only bounded,
    purpose-built evidence packs. Historical ActivityWatch range tools receive
    the Run's frozen time anchor at execution and reject any window ending after
    it, so a model cannot silently turn a past-time request into a future query.
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
23. Cockpit has one unified, read-only Watch destination for personal-state
    understanding; the former standalone status-weather page is removed. Watch
    presents observed ActivityWatch facts, exact statistics, Chinese narrative
    summaries, and a read-only GitHub/Gmail/Google Calendar auto-fetch feed
    without triggering a fetch. It contains no ActivityWatch state inference,
    comprehensive state assessment, confidence hypothesis, or inference-evidence
    surface. Raw and connector text is visibly untrusted, is inspectable only
    through bounded reads, and never becomes a command surface. Companion
    micro-weather and RhythmPolicy remain separate presentation/execution
    concerns and do not acquire an ActivityWatch inference path.
24. An Automation is a persisted schedule that submits an ordinary idempotent
    Run. It cannot execute tools directly, create a second workflow engine, or
    bypass the Run Coordinator, frozen capability snapshot, Trust Plane, or
    approval lifecycle. Missed schedules coalesce instead of replaying a burst.
25. A Skill selected from a local catalog is installed explicitly as an
    immutable verified Workspace snapshot. The source checkout is not a runtime
    dependency, installation does not grant authority, and changes apply only
    to future Runs. A renderer click creates a durable install Action and
    Approval; request booleans are never authority, and execution starts only
    after the persisted user decision.
26. Desktop-managed MCP connections come from a curated, version-pinned catalog
    and require explicit installation and enablement. Renderer input cannot
    supply arbitrary commands or environment variables. MCP tools remain
    subject to Workspace scopes and execution-time Trust checks, and connection
    changes affect only future Runs. The package installer receives the real
    approved Action id; an interrupted installation enters `NEEDS_REVIEW` and
    is never automatically retried during recovery. A healthy enabled preset
    contributes only its fixed `mcp:{preset}:use` effective scope while a new
    capability snapshot is resolved; this derived scope comes from durable
    enabled state plus the curated catalog, never from server annotations.
    Discovery also fails closed when a server exposes any tool outside the
    preset's Python-owned tool-name allowlist. Stateful presets may write only
    to their own Workspace-private internal state root; those files participate
    in the matching explicit privacy-reset category and never make a Workspace
    action root writable. The desktop catalog presents runnable presets rather
    than disabled roadmap cards. Offline Python-owned Time and read-only Git
    presets run through the bundled WeatherFlow runtime inside the same MCP
    Seatbelt boundary; network-bound presets remain absent until their dedicated
    redirect-safe egress boundary exists.
27. Cockpit groups user-managed agent facilities in one left-navigation Tools
    section: Automations, Skills, MCP Servers, LLM Models, and Composio. System
    and privacy preferences remain in Settings; conversation remains primary.
28. Conversation sessions are durable Workspace-scoped presentation groupings.
    A Run may belong to one session, but session rename or pin state never
    changes the Run, its frozen routes, capability snapshot, or authority.
    Session mutation and session-filtered Run queries require the owning
    Workspace identity and fail closed on a mismatch. Deleting a session is a
    privacy deletion: it removes the session, all of its Runs, their events,
    checkpoints, actions, approvals, routes, continuations, artifact manifests,
    and unreferenced artifact bytes in one explicit deletion flow. It never
    degrades into detaching Runs with a null session.
29. An OAuth catalog entry describes a brokered account identity, not an Agent
    capability. Automatic fetch and conversation tools stay unavailable until
    WeatherFlow ships explicit reviewed contracts for that toolkit.
30. Provider tool-call IDs are untrusted correlation hints, not Action
    identities. A side-effect Action is idempotent only for the same Run, model
    step, batch position, frozen tool, and canonical arguments. Recovery consumes
    a persisted successful Action result without replaying the side effect.
31. Brokered tool responses cross into model context only through an explicit
    action-specific output projection. Unknown fields, credential-bearing text,
    and URL query or fragment data fail closed instead of relying on a secret-key
    blacklist.
32. Trust Policy, not a tool name, decides the durable side-effect boundary.
33. Model-visible tools are selected through exactly two Run-scoped modes.
    `ask` exposes only reviewed `observe` and `network_read` ToolSpecs from the
    current Workspace's installed capabilities and active connector identities;
    `bypass` exposes the complete reviewed surface. The selected mode is stored
    on the Run and frozen into its capability snapshot. It never bypasses
    Workspace isolation, connector identity checks, OS sandboxing, Trust Policy,
    Action persistence, or Approval. Connector bindings no longer carry a
    separate conversation tool grant; they own connection identity and optional
    background-fetch settings only.
    Every call classified as `SANDBOX` or `APPROVE` must own an Action before
    execution. A timeout or cancellation after execution starts moves both the
    Action and Run to `NEEDS_REVIEW`; cancelling an async wrapper does not prove
    that a worker thread or child process stopped. Only `ALLOW` calls may use the
    lightweight no-Action path.
33. A finite model-cost budget is enforceable only from provider-reported usage
    and an exact entry in a versioned pricing catalog for the frozen provider,
    model, and user-confirmed billing origin. The endpoint hostname never selects
    a billing product. Global PayGo USD and mainland PayGo CNY are independent
    catalogs, native currency is preserved without FX conversion, and
    `cost_scope` is always `model_usage_only`. Token Plan, Credits, unconfirmed
    billing type, non-USD `max_cost_usd`, unknown pricing, or missing usage fails
    closed before tool dispatch or terminal result commit; none is interpreted as
    zero cost.
34. Executor output is untrusted until it validates against the frozen
    `ToolSpec.output_schema` under JSON Schema Draft 2020-12. Invalid safe-read
    output becomes a value-free failure Observation. Invalid output from a
    side-effect Action moves the Action and Run to `NEEDS_REVIEW`, clears the
    unusable persisted result, and is never replayed into model context or
    re-executed during recovery. An empty schema remains an explicit
    accept-anything compatibility contract.
35. Runtime shutdown is an ownership boundary: stop background producers, cancel
    and await every daemon-owned Run task, and only then close tool transports.
    A terminally closed RuntimeContainer rejects new Run or connector tasks so no
    task or database worker can outlive its event loop.
36. `SANDBOX` is an execution boundary, not a Trust label. Project commands,
    scripts, builds, and tests execute only through the typed Python-owned
    `SandboxBackend`. The macOS backend applies an OS-enforced default-deny
    profile, an isolated environment and temporary home, explicit read/write
    roots, offline networking by default, resource/output limits, and process-
    group termination. Backend absence or failed confinement fails closed; there
    is no ordinary-subprocess fallback.
37. ActivityWatch is the sole raw activity fact source. It is installation-scoped
    personal telemetry outside WeatherFlow's lifecycle and remains available
    while the Agent is stopped or restarting. WeatherFlow is strictly read-only:
    ordinary access uses the loopback REST API, while an explicitly selected
    historical-analysis or diagnostic fallback may open the configured SQLite
    file through a short-lived `mode=ro`, `query_only` connection. No permanent
    database connection or internal ActivityWatch table contract is allowed.
38. WeatherFlow stores no ActivityWatch application names, titles, URLs, AFK
    events, or other raw intervals in its own database. Its activity domain owns
    only derived task, attempt, summary revision, statistical,
    Category-rule-version, source-health, dependency, and evidence-reference
    records. An ActivityWatch evidence reference identifies the bucket, event,
    timestamp, duration, and digest needed to reproduce a narrative claim. A
    connector summary evidence reference identifies the GitHub, Gmail, or Google
    Calendar source, replaceable snapshot watermark, opaque source item, fields
    used, and digest without copying provider raw text into the activity ledger.
39. The `Asia/Shanghai` summary schedule is fixed and enumerable: four six-hour
    stages per day, a distinct rolling 24-hour summary ending at 06:00, Monday
    calendar weeks, anchored 14-day periods, and calendar months. A durable,
    deterministic task exists for every eligible window. Startup reconciliation
    probes ActivityWatch, discovers its available range, enumerates all
    theoretical windows, and retries missing, failed, interrupted, or non-final
    work in chronological order without using a single "last summary" cursor.
40. Window completion is not immediate finality. A provisional revision may be
    generated after a 15-minute grace period; finalization waits at least 60
    minutes and re-queries the same raw window. Changed evidence produces another
    revision instead of mutating history. Task claims, attempts, revisions, and
    finalization are idempotent and safe across duplicate starts.
41. ActivityWatch Category is a query-time derivation, never a raw event field.
    Every derived result records the normalized Category-rule snapshot and its
    digest. Old revisions remain reproducible and are either marked as using old
    rules or explicitly re-generated under a new version.
42. Activity titles, URLs, and document names are untrusted evidence. Before any
    model request, deterministic credential detection removes userinfo,
    authentication codes/tokens, cookies, signed URL material, and secret-shaped
    text. The model receives only bounded statistics, limited ActivityWatch
    evidence excerpts, bounded read-only GitHub, Gmail, and Google Calendar
    snapshot excerpts, and optional lower-level summaries inside explicit
    untrusted-data delimiters; it receives no tools or execution authority.
43. ActivityWatch contributes observed facts and recomputable statistics only.
    WeatherFlow does not generate or store ActivityWatch-derived programming,
    communication, meeting, focus, context-fragmentation, confidence, or other
    state hypotheses. There is no comprehensive ActivityWatch state assessment,
    inference ledger, inference semantic operation, or inference HTTP endpoint.
44. Activity-summary generation settings are installation-scoped and
    persistent. Users may select a model from an existing Workspace model
    configuration but cannot view or edit the summary prompt. Every summary uses
    one built-in, digest-versioned Simplified-Chinese prompt and produces Chinese
    narrative only. Settings never store prompt text, credential material, or a
    credential reference. Every revision records the effective provider,
    model-configuration version, summary-settings version, and prompt version.
45. Every summary request independently considers bounded, read-only snapshots
    from all three production auto-fetch sources: GitHub, Gmail, and Google
    Calendar. Missing, disabled, stale, or failed sources remain explicit
    coverage states and are never interpreted as no activity. Summary revisions
    record per-source snapshot watermarks and evidence refs; ActivityWatch
    statistics are still recalculated from ActivityWatch rather than from
    connector text or lower-level summaries. All generated summary and
    connector-synopsis prose is Simplified Chinese; source-language text may
    appear only as visibly quoted, bounded, untrusted evidence.
46. A configured activity model's malformed, schema-invalid, non-Chinese,
    inference-bearing, or source-echoing final output is rejected as
    `activity_model_output_rejected` with the bounded stage `model_output`. The
    attempt becomes a permanent failure until explicit regeneration and creates no deterministic replacement
    revision. Provider response-envelope failures remain non-retryable and
    record only one bounded failure stage (`http_response`, `provider_status`,
    `choice`, `message`, `empty_text`, or `unknown`) on the attempt. No provider
    message, status text, response body, ActivityWatch content, or credential is
    persisted; authentication, network, and route failures have no response stage.
47. A production-security benchmark may report overall `PASS` only when every
    required real macOS Seatbelt case executed and `skipped=0`. External-network
    denial requires an unsandboxed host reachability positive control against the
    same target; target unreachability invalidates the case instead of counting as
    sandbox enforcement.
48. Production-metrics artifacts are evidence-eligible only when the runner
    preflights one clean source commit, freezes that commit identity for the
    benchmark, and verifies both a clean worktree and the same commit again after
    execution and immediately before writing artifacts. A dirty or changed source
    fails closed without producing a report.

## 4. v3.0 scope

v3.0 includes the Python daemon, Tauri three-surface desktop, durable harness,
Rhythm Intelligence, risk-based supervised autonomy, Developer/Research/
Personal Operations capability packs, Skills, MCP, Agent Definitions,
schedule-to-Run Automations, local ownership, diagnostics, and macOS packaging.

v3.0 excludes Windows/Linux support, mobile/cloud/team features, screenshots,
keystroke or clipboard capture, ambient audio, recursive agent networks, a
workflow canvas, broad email or messaging catalogs beyond the bounded
first-party Gmail connector, and all v2 compatibility. Read-only ActivityWatch
integration, local derived analytics, automatic hierarchical summaries, and
bounded consented model analysis are included. WeatherFlow-owned activity
watchers and a second raw activity vault are excluded.

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
  Provider reasoning is excluded from domain state; an unconfigured production
  Run parks in `WAITING_USER` with a model-configuration requirement and never
  fabricates an Echo success. Echo is an explicitly injected test adapter only.
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
  Runs, unified Watch, integrations, and settings. The floating Companion
  remains the primary habit surface and Cockpit remains explicit-only.
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
  grant of Agent authority. The minimum scoped key therefore needs `Auth configs`
  read/write, `Connected accounts` read/write, `Toolkits` read, and
  `Tool execution` write, with all other Composio permission areas disabled.
  Managed OAuth uses v3 Connect Link only; no legacy
  initiate/v1/v2 fallback, generic
  Composio model tool, Trigger lifecycle, WeatherFlow account login, or cloud
  backend is introduced. Connection never grants execution authority.
- 2026-07-17: Corrected the Composio scoped-key, diagnostic, and replacement
  contract to match the broker authority boundary. A Composio transport 401 is
  `broker_auth` and means the project key is invalid; transport 403 is
  `broker_permission` and means the key is valid but lacks a required scoped
  permission. A wrapped provider 401/403 or `auth_refresh_required` remains
  `auth` and requires provider OAuth recovery; missing project OAuth application
  setup remains `auth_config_required`. After a replacement key validates and is
  persisted, WeatherFlow clears credential-scoped stale errors and immediately
  schedules read-only revalidation of every stored connected-account reference.
  Authoritatively verifiable same-project connections are preserved. A reference
  that is inaccessible or belongs to another project becomes `project_changed`
  and requires OAuth again, but WeatherFlow never remotely revokes or deletes it
  because the old project may still own that connection.
- 2026-07-14: Reframed Cockpit's status-weather destination as a read-only
  personal insight surface. The page has exactly three product roles: show the
  current human-state weather and dimensions, summarize recent activity/task
  behavior, and display only active long-term profile assertions with confidence
  and evidence counts. The former check-in/correction form was removed because
  conversation is the primary deliberate-input surface. The activity-source and
  screen-time ownership portion of this decision is superseded by the later
  ActivityWatch read-only decision.
- 2026-07-17: Superseded the standalone status-weather destination with one
  unified Watch surface. Companion micro-weather and RhythmPolicy remain, but
  Cockpit no longer duplicates them as a low-value page. Watch now owns the
  evidence-backed human-state presentation: current ActivityWatch facts,
  Workspace-scoped model assessment over the last two hours plus today's
  Asia/Shanghai Calendar, and a read-only GitHub/Gmail/Calendar auto-fetch feed.
  Connector snapshots remain replaceable connector-domain context; mixed
  assessments persist only aggregate statistics, model/prompt provenance, and
  source evidence references, never raw ActivityWatch or Calendar text. The
  model-assessment and mixed-assessment portion of this decision is superseded
  by the later summary-only ActivityWatch decision.
- 2026-07-17: Removed unwired legacy GitHub-release and Research ToolSpecs from
  the production catalog instead of advertising permanent unavailable entries;
  they remain injectable typed-provider contracts only. New and existing
  Workspaces receive the authority-free `personal_operations` pack
  idempotently. Its Calendar-backed tools appear only with an active Google
  Calendar identity and execute through the reviewed Composio action/version
  and frozen per-Run connector route. `extensions.install` reuses the explicit
  Workspace-write scope but remains an `install` Action requiring approval and
  never grants extension-requested scopes.
- 2026-07-14: Added durable Workspace-scoped conversation sessions for Cockpit
  history management. Sessions may be empty, renamed, and pinned; new Runs may
  reference one session while historical Runs remain valid without a session.
  Pinning is presentation metadata only and grants no runtime authority.
- 2026-07-14: Defined conversation deletion as a Workspace-scoped privacy
  operation. The daemon cancels owned background work, transactionally removes
  the session and all Run-owned operational/audit data, and then removes each
  content-addressed artifact blob only when no surviving Run in that Workspace
  still references it. Cross-Workspace deletion reports not found.
- 2026-07-14: Added a shell-local Cockpit theme preference with explicit
  `system`, `light`, and `dark` choices. The renderer applies the saved
  `weatherflow.theme` value before React mount and follows macOS appearance only
  in `system` mode; theme state does not cross into Python domain storage.
- 2026-07-14: Closed the renderer's unauthenticated bridge fallback. Product
  startup now resolves the native `daemon_bridge` command in every mode and
  fails closed when it cannot obtain its per-launch token; isolated browser
  tests must inject an explicit bridge configuration.
- 2026-07-13: Standardized macOS development on a stable local code-signing
  requirement. `pnpm dev:app` signs Cargo's final debug executable immediately
  before launch with the fixed identifier `ai.weatherflow.desktop.dev` and a
  fixed local certificate; ad-hoc/linker signatures are not accepted. The
  one-time setup certificate is development-only and does not replace release
  Developer ID signing or notarization. This keeps Keychain/TCC authorization
  stable across rebuilds without changing credential ownership or exposing
  secret material.
- 2026-07-14: Approved the Cockpit Tools surface and schedule-to-Run Automation
  contract. Users may explicitly install verified immutable Skill snapshots
  from the local `wesley-skills` catalog, install and enable version-pinned MCP
  presets, and manage Automations alongside LLM and Composio configuration.
  Automations only submit ordinary Runs through the existing coordinator;
  Skills and MCP remain descriptive capability inputs and never grant authority.
- 2026-07-14: Refined the floating Companion into one compact, fixed square
  weather tile. The tile remains the single click-or-drag target and keeps the
  weather glyph visually dominant; the native window is tightly fitted to the
  visible tile so transparent margins do not create a hidden pointer-catching
  region. Hover feedback changes only surface, border, and elevation and never
  shifts the tile's position. Run and sensor state remain small secondary dots.
- 2026-07-14: Promoted brokered OAuth connections from background context only
  into the frozen Capability Plane. Connection identity and automatic fetch are
  separate settings. Only curated canonical WeatherFlow ToolSpecs map to
  reviewed Composio action slugs and toolkit versions; no generic execute/meta
  tool is exposed. A Run freezes its opaque connected-account identity and
  selected ToolSpecs, then rechecks account identity and scope at execution.
  Reads may execute directly; writes and destructive actions always persist
  Action/Approval first. Account changes fail closed for old Runs.
- 2026-07-15: Corrected the production Composio execution contract. Every broker
  call now carries the stable WeatherFlow installation user ID together with the
  opaque connected-account ID, and reviewed actions pin their own current
  toolkit version instead of sharing one invalid cross-toolkit version. The
  curated GitHub surface now includes repository and commit discovery alongside
  identity, issue, pull-request, and branch operations; Gmail and Google Calendar
  retain their reviewed read/write surfaces. Every external write still
  persists Action and Approval before broker dispatch. Activating a new connection
  may upgrade an older Composio-managed Auth Config to the full reviewed action
  allowlist only after
  connected-account ownership, toolkit, and active state are revalidated;
  user-provided Auth Configs are never rewritten.
- 2026-07-15: Replaced per-connector conversation grants with two explicit
  Run-scoped tool modes selected from the conversation composer. `ask` is the
  fail-closed default and freezes only `observe` and `network_read` tools across
  installed Packs, enabled MCP presets, and every active connector in the
  selected Workspace. `bypass` freezes the complete reviewed tool surface but
  does not weaken the Trust Plane: workspace writes and command execution still
  use the OS sandbox, while external writes, installs, and destructive actions
  still persist Action/Approval before dispatch. Connector bindings remain
  Workspace-scoped account identities and background-fetch configuration; the
  former `disabled`/`read`/`read_write` fields and endpoint are removed from the
  v3 contract, and migration strips persisted remnants. Each Run stores its mode so
  retries, resume, Workers, and audit output cannot inherit a later UI toggle.
- 2026-07-14: Closed inherited-tool routing gaps for MCP and Worker Runs. A
  healthy enabled curated MCP preset contributes its fixed effective use scope
  only while future capability snapshots resolve; server annotations still
  cannot grant authority. A leaf Worker whose frozen child snapshot contains
  reviewed read-only Composio tools receives an exact copy of the parent Run's
  corresponding connector route only after Workspace, account identity, grant
  revision, tool allowlist, and scopes are revalidated. Child snapshots without
  those tools receive no connector route, and connector writes remain forbidden.
- 2026-07-14: Adopted the useful core semantics of pi-agent without replacing
  WeatherFlow's durable Run shell: provider-neutral typed turns, ordered
  multi-tool batches, checkpoint-before-dispatch, full JSON Schema validation,
  per-tool timeout, cancellation barriers for uncertain side effects, durable
  usage/cost accounting, and bounded follow-up context projection. WeatherFlow
  retains frozen per-Run model/tool/connector routes and its Trust/Rhythm planes;
  pi-style streaming lifecycle events, steering queues, and compaction remain
  extensions of this single SharedTurnLoop, never a second agent loop.
- 2026-07-14: Expanded the brokered account directory to twenty curated
  Composio OAuth toolkits while keeping capability support explicit. GitHub,
  Gmail, and Google Calendar remain the only entries with production automatic
  fetch and reviewed model-visible ToolSpecs. Before creating managed auth,
  WeatherFlow checks the authoritative project toolkit record and always
  restricts the Auth Config to a non-empty reviewed action allowlist. Missing
  managed auth or a missing reviewed allowlist requires a user-provided Auth
  Config and fails closed; connection alone never exposes tools.
- 2026-07-14: Hardened the durable side-effect boundary against repeated or
  malformed provider call IDs. Runtime Action keys now bind the Run, model
  step, batch slot, frozen tool, and canonical arguments; ApprovalCoordinator
  rejects any idempotency-key identity mismatch. A recovered `SUCCEEDED` Action
  contributes its persisted result as the missing Observation and is never
  executed again. Composio results now use reviewed per-action output
  projections with credential-text redaction and query-free URLs before they
  enter checkpoints or model context.
- 2026-07-14: Extended the Action barrier to all Trust Policy `SANDBOX` and
  `APPROVE` decisions. Sandboxed workspace writes and command execution are
  durably system-authorized before dispatch, and timeout or cancellation after
  dispatch becomes `NEEDS_REVIEW` because cancellation cannot establish that a
  thread or process stopped. Added the versioned MiniMax pay-as-you-go pricing
  catalog `minimax-paygo-2026-07-14`; finite cost budgets now use provider usage
  only when the frozen model and official billing origin have a known price and
  otherwise fail closed before tools or terminal output are committed.
- 2026-07-14: Added Draft 2020-12 validation at the Tool Observation boundary.
  Safe read tools replace invalid executor output with value-free validation
  diagnostics. Side-effect output is validated while its Action is still
  `EXECUTING`; a mismatch transitions Action and Run to `NEEDS_REVIEW` without
  persisting the returned value. Recovered historical `SUCCEEDED` Actions are
  revalidated before their result enters the checkpoint; invalid results are
  cleared and never replayed. Reviewed Composio tools now publish strict,
  action-specific output schemas for their projected result envelopes.
- 2026-07-14: Added first-party OpenAI Responses and Anthropic Messages model
  adapters without adding another agent loop or credential path. `openai` and
  `anthropic` are fixed native credential providers with renderer
  `set`/`delete`/`status` and daemon-only private-socket `resolve`. OpenAI uses
  stateless `store=false` Responses calls and Anthropic uses the versioned
  Messages API. Provider reasoning items, signed thinking blocks, and exact
  tool-use messages required for a later turn are retained only as encrypted,
  Run/model-bound provider continuations; normalized text, tool calls, and
  provider-reported usage remain the only data admitted to SharedTurnLoop state.
  Workspace selection still freezes one explicit provider/model route per Run;
  no automatic model routing was introduced.
- 2026-07-14: Hardened daemon and provider boundaries after the v3 audit. The
  Python listener now rejects non-loopback bind addresses, explicit bridge
  tokens cannot be empty, and model base URLs cannot carry userinfo, query, or
  fragment credentials. Provider, connector, and safe-tool failures expose only
  typed value-free diagnostics; background connector snapshots apply the same
  credential-text and URL sanitization as reviewed tool output. The local
  security scan now covers Run, Action, Approval, Automation, connector, model,
  and streamed artifact content in addition to events, checkpoints, and memory.
- 2026-07-15: Made OS confinement a first-class Python runtime boundary and
  approved `core/src/weatherflow/sandbox/` as a v3 top-level domain. The first
  macOS backend uses the host Seatbelt facility behind a typed, replaceable
  `SandboxBackend`; it must probe availability and fail closed because its
  current `/usr/bin/sandbox-exec` launcher is deprecated. Profiles start from
  default deny, expose only authorized Workspace roots plus reviewed read-only
  toolchain roots, use an ephemeral HOME, deny external networking and host
  process signaling, and enforce wall/CPU/file/fd/output limits. This is the
  only path that may unlock project scripts, builds, and tests; unsandboxed
  subprocess execution is not a compatibility fallback. In parallel, Agent Core
  stays one `SharedTurnLoop` with pi-agent-style typed turns/events and small
  composable seams; durable Run, Trust, Action, Approval, checkpoint, and frozen
  route ownership remain WeatherFlow's outer shell rather than being folded into
  a second workflow engine. The first C1 extraction adds a provider-neutral
  `AgentCore.next_turn` boundary for bounded model retry/turn validation and a
  `TurnCommitter` as the checkpoint-before-dispatch/event commit barrier; neither
  is a second loop or state authority. `ToolDispatcher` now owns the validated
  Trust/Action/Approval/execution/Observation path, leaving SharedTurnLoop as the
  small ordering coordinator. Durable `run_controls` add `steer` and `follow_up`
  inputs without process-local queues: steering is applied before the next model
  request, while follow-up is applied in the same transaction that would
  otherwise commit a final result. Applied controls and the checkpoint advance
  atomically, so restart cannot replay input and final-result races fail closed.
  Sandbox build caches use a private offline Cargo home with read-only
  registry/Git cache links only, and local Unix sockets remain scoped to the
  private temp root or authorized writable roots.
- 2026-07-15: Closed the remaining managed MCP subprocess bypasses and added
  durable Agent Core lifecycle projections. Fixed-version npm installation now
  runs only in an approved HTTPS-only sandbox request, while managed stdio MCP
  servers are spawned by the same backend with preset-specific read roots,
  offline networking, and no writable Workspace roots. A missing backend marks
  the connection unavailable. Playwright remains catalog-visible but unavailable
  until a redirect-safe public-network broker exists. Sandbox startup performs
  and caches a real read/write escape-denial probe; profiles deny descendant
  `setsid`/`setpgid`, and a fixed non-interpolating resource launcher replaces
  Python `preexec_fn`. AgentCore now projects model start, retry, completion, and
  terminal provider failure without putting provider-private content in Events.
  Host acceptance passed 522 Python tests plus every eval, hardening, desktop,
  production-build, and Rust gate. A second complete `make check` executed
  through `DeveloperExecutor -> MacOSSeatbeltSandbox` with loopback-only
  networking and return code 0, proving the repository can build and test itself
  inside the new OS boundary.
- 2026-07-15: Expanded the curated MCP catalog without weakening the subprocess
  boundary. The official npm Knowledge Graph Memory preset is the only newly
  runnable server: it is offline, tool-name allowlisted, and can write only its
  Workspace-private MCP state directory, which is included in explicit memory
  and Workspace privacy resets. Time, read-only Git, and Context7 remain visible
  but unavailable until the packaged app owns, respectively, a separate Python
  MCP runtime, safe multi-root repository routing, and redirect-safe host-bound
  egress. The approved npm installer resolves `node` and `npm` from one fixed
  runtime prefix, exposes that prefix read-only, and exposes only its private
  versioned temporary destination as writable/readable application data; it no
  longer exposes the whole Workspace internal root. Host `uvx` and unrestricted
  HTTPS are not fallback paths.
- 2026-07-16: Promoted complete personal activity history into a first-class v3
  product surface. Consented macOS and browser watchers now target an
  installation-scoped Raw Activity Vault containing full application, window,
  URL, tab, focus, and active/idle intervals. Cockpit owns a visually rich
  screen-time component and detailed activity explorer. A separate persisted
  opt-in permits audited, credential-scrubbed, tool-free remote state inference
  at every `Asia/Shanghai` hour from 06:00 through 24:00; missed hours coalesce
  and inference evidence references vault event IDs without copying raw content
  into Runs, the Event Ledger, memory, artifacts, or ordinary diagnostics. This
  source-ownership, watcher, vault, and hourly-schedule portion is superseded by
  the later ActivityWatch read-only decision; the product goal of a first-class
  visual activity surface remains.
- 2026-07-16: Closed the first desktop usability repair pass. Conversation
  chrome is compact and never permanently consumes the reading area; semantic
  icon surfaces follow the selected light/dark theme. The MCP catalog now shows
  only runnable presets: npm servers receive their verified Node runtime as an
  explicit read-only sandbox root, while Time and read-only Git use a bundled
  Python-owned stdio MCP server under the same offline Seatbelt boundary.
  Playwright, Fetch, and Context7 remain backend-known but are not advertised as
  installable until redirect-safe host-bound egress exists. Screen-time queries
  refresh while visible. Development launch fingerprints Cargo's linked bytes
  and reuses a stable signed runtime copy until the next Rust relink, while
  startup credential-presence checks are attribute-only, suppress
  authentication UI, and never resolve secret material.
- 2026-07-16: Consolidated Cockpit appearance onto one warm-neutral semantic
  palette shared by light and dark modes. Terracotta owns primary interaction,
  ochre/gold owns observation and browser activity, sage owns healthy state, and
  warm taupe owns secondary surfaces. Dark surfaces are espresso/warm charcoal,
  not neutral black; cold blue is not a Cockpit semantic color. OAuth vendor
  marks keep their source icon shapes but inherit reviewed theme tones so
  provider, automation, settings, activity, and integration surfaces remain
  visually coherent.
- 2026-07-16: Replaced the WeatherFlow-owned Raw Activity Vault, macOS sampler,
  and browser watcher with a strict read-only ActivityWatch integration.
  ActivityWatch now remains the sole raw fact source and independent collector.
  WeatherFlow owns only a derived activity database containing source health,
  fixed-window task ledger entries, attempts, summary revisions, statistics,
  Category-rule snapshots, dependencies, and reproducible evidence references.
  Startup probes and reconnects to ActivityWatch, enumerates
  every theoretical `Asia/Shanghai` six-hour/daily/weekly/biweekly/monthly
  window, and backfills missing or non-final tasks chronologically. A 15-minute
  provisional and 60-minute finalization boundary protects against delayed
  heartbeats; model input is bounded, credential-scrubbed, explicitly untrusted,
  and tool-free. A locked or temporarily unavailable model credential fails the
  current attempt into `needs_retry` without writing a deterministic revision;
  compensation retries the selected model after credential access recovers.
  Any former fact-versus-hypothesis and inference portion of this decision is
  superseded by the 2026-07-18 summary-only contract.
- 2026-07-19: Preserved historical deterministic summary revisions created by
  transient model authentication or connectivity fallback, while idempotently
  requeuing only tasks whose latest revision has that transient marker. Recovery
  appends a selected-model revision after credentials return; route-unavailable,
  no-coverage, rejected-output, and already-recovered revisions remain untouched.
- 2026-07-19: Tightened activity-summary model routing and authentication
  diagnostics. A configured summary selection must exactly match the current
  Workspace provider and model-configuration version. Its independently selected
  model may differ from the Workspace conversation model, but it reuses only that
  verified configuration's provider, base URL, and credential reference. Provider
  or version drift is the retryable typed failure
  `activity_model_route_version_mismatch`, never a silent route substitution.
  Native credential resolution failures are recorded as
  `activity_model_credential_unavailable`, while an authenticated provider
  transport that rejects the key is recorded separately as
  `activity_model_provider_authentication_failed`.
- 2026-07-19: Removed the activity analyzer's deterministic fallback for a
  configured model that returned a tool-free final turn but failed the fixed
  JSON, Chinese-narrative, inference, evidence, or source-echo contract. The
  attempt now fails non-retryably as `activity_model_output_rejected`, writes no
  revision, and can be run again only through explicit regeneration. Provider
  response errors likewise stay non-retryable while exposing one bounded,
  content-free failure stage in the attempt ledger; runtime code never derives
  that stage by parsing an exception message.
- 2026-07-17: Added installation-scoped activity-summary generation settings.
  The user may select a model backed by an already configured Workspace model
  route and edit bounded summary guidance in Settings. The activity ledger
  stores only the source Workspace identity, provider/model names, configuration
  and settings versions, prompt text/version, and timestamps; API keys and
  credential references remain outside this table. Editable guidance cannot
  replace the fixed untrusted-evidence, no-tools, and validated-output contract.
  The editable-guidance and persisted-prompt-text portion of this decision is
  superseded by the following fixed-prompt decision.
- 2026-07-17: Replaced editable ActivityWatch guidance and all ActivityWatch
  state inference with one built-in, digest-versioned Simplified-Chinese summary
  contract. Users may select the summary model but cannot view, submit, or store
  custom prompt text. Each tool-free summary request includes bounded sanitized
  ActivityWatch evidence plus independently bounded read-only snapshots from
  GitHub, Gmail, and Google Calendar; it records ActivityWatch evidence refs and
  per-source connector snapshot evidence refs. Missing or stale connector
  coverage is explicit. Summary output is Chinese narrative only. The former
  programming/communication/meeting/focus/context-fragmentation hypotheses,
  comprehensive Watch state assessment, inference tables, semantic operations,
  HTTP endpoints, and confidence UI are removed. This supersedes the inference,
  mixed-assessment, and editable-guidance portions of the 2026-07-16 and earlier
  2026-07-17 activity decisions while preserving the ActivityWatch sole-source,
  strict read-only, bounded-context, untrusted-data, and no-tools boundaries.
- 2026-07-18: Confirmed and tightened the ActivityWatch summary-only contract.
  The fixed Simplified-Chinese prompt is code-owned and digest-versioned; its
  text is not a Settings field, request input, or persisted setting. Settings
  retain only a user-selected valid model route and its version. Every summary
  independently includes bounded read-only GitHub, Gmail, and Google Calendar
  snapshot coverage, records per-source evidence refs/watermarks, and exposes
  source absence or staleness rather than silently substituting GitHub alone.
  Generated connector synopsis prose is Simplified Chinese, while any retained
  source-language text is visibly quoted bounded untrusted evidence.
  All ActivityWatch state inference, comprehensive assessment, inference
  records, semantic operations, HTTP endpoints, and Watch confidence surfaces
  are forbidden. This decision overrides every earlier activity decision that
  permits editable summary guidance, prompt persistence, or inferred human
  state, while retaining raw-source immutability, explicit untrusted-data
  delimiters, tool-free model calls, and strict read-only access.
- 2026-07-17: Froze relative-time interpretation to each durable Run's
  `created_at`. The orchestrator exposes that instant to the selected model in
  UTC and `Asia/Shanghai`, so today, yesterday, the last two hours, and the past
  24 hours remain traceable and cannot drift when a Run resumes after restart.
  An explicitly user-supplied timezone still takes precedence.
- 2026-07-18: Fixed the three production connector fetchers to independently
  enableable, read-only daily refreshes (`1440` minutes). GitHub now reads
  unread notifications from a seven-day overlap plus bounded recent activity;
  Gmail reads only thirty-day unread metadata and bounded preview snippets and
  never stores `messageText` or payload bodies; Google Calendar reads a bounded
  window spanning seven past and fourteen future Asia/Shanghai days across all
  accessible calendars. A non-empty provider response that normalizes to zero
  records is `invalid_response` and cannot overwrite the last successful
  snapshot. Watch feed source metadata exposes only the stable strategy and
  coverage keys, next refresh, aggregate raw/normalized counts, and
  normalization health; credentials and provider account identities remain
  outside the projection.
- 2026-07-19: Slimmed the completed v3 tree without changing product or storage
  ownership. Deterministic flagship-eval helpers now live only under tests;
  production activity-summary modules and contracts use summary terminology.
  Replaced the unconsumed standalone Rhythm Insights read model with a narrow
  Watch-only active Profile Assertion projection; removed desktop wrappers
  superseded by the combined Watch dashboard request, the v2 activity-metadata
  request tombstone, and unreachable remote-activity snapshot methods. Existing
  migrations, ActivityWatch semantic queries, Watch, recovery, and the flagship
  acceptance gate remain intact. Superseded implementation plans and design-QA
  outputs remain recoverable from Git history rather than the active tree.
- 2026-07-21: Replaced endpoint-derived MiniMax pricing with an explicit frozen
  `billing_origin`. Global PayGo uses its official versioned USD catalog;
  mainland PayGo uses a separate official versioned CNY catalog with no FX
  conversion. Token Plan and unconfirmed billing remain monetary `UNKNOWN`, and
  finite USD budgets fail closed for non-USD amounts. Run usage now exposes
  `cost_amount`, `currency`, `cost_usd`, and the fixed
  `cost_scope=model_usage_only`. Production-security reports also require every
  real Seatbelt case to execute (`skipped=0`), and external-denial evidence now
  includes a host reachability positive control to the same target. Production
  metrics freeze one clean source commit and revalidate it before artifact write;
  dirty or commit-changing runs cannot produce evidence reports.
