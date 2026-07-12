# WeatherFlow v3 Design Specification

- **Date:** 2026-07-12
- **Status:** Approved design
- **Target:** macOS-first v3.0
**Strategy:** Clean-slate rewrite; no v2 code or data compatibility

**Authority boundary:** `weatherflow-architecture-v2.md` remains authoritative
for the existing v2 runtime until P0 begins. This specification is authoritative
for the approved v3 replacement design only. Before any v3 implementation edit,
P0 must create `weatherflow-architecture-v3.md`, update `AGENTS.md` to point to
it, and record the supersession explicitly.

## 1. Executive summary

WeatherFlow v3 is a **rhythm-aware personal agent OS**. It remains centered on
understanding the human's current state, but gains a general-purpose agent
harness so the user can delegate meaningful work instead of only receiving
observations.

The product has three defining properties:

1. **Human state is a runtime input.** Rhythm intelligence affects planning,
   interaction density, delegation, and scope recommendations. It is not only a
   label or desktop animation.
2. **The desktop companion is the primary habit surface.** A quiet floating
   companion communicates human state through micro-weather and accepts commands
   through a Spotlight-style input capsule. It never opens the full application
   without an explicit user action.
3. **A small Python harness is the sole business core.** It owns durable runs,
   agents, tools, skills, policy, approvals, memory, artifacts, and background
   execution. Tauri owns native desktop presentation and OS bridging only.

WeatherFlow v3 is not an incremental refactor. The existing application is
archived through Git history/tagging and replaced with a new architecture. There
is no compatibility layer for v2 APIs, SQLite data, profile files, or desktop
behavior.

## 2. Approved product decisions

The following decisions are binding for v3.0.

### 2.1 Product identity

- WeatherFlow is a **rhythm-aware personal agent OS**, not a neutral agent SDK.
- General capability exists to make interaction useful and frequent; it is not
  an end in itself.
- Rhythm awareness remains the differentiator shared by every built-in and
  installed agent.
- Goal-driven execution and state-driven assistance are supporting capabilities.
  The desktop companion experience is the primary product line.

### 2.2 Desktop interaction

- Use a **dual-surface model**:
  - a floating companion for ambient presence and fast input;
  - a full Cockpit for tasks, approvals, artifacts, history, and settings.
- Human state is rendered as **micro-weather around a stable character**.
- Agent work state is rendered separately through an outer ring, badge, and
  small motion. Agent state never replaces human-state weather.
- Clicking the character or using a global shortcut opens a **pure input
  capsule**. The capsule contains no recommendations, history, rhythm summary,
  or task timeline.
- Submitting a command immediately closes the capsule.
- The Cockpit **never opens automatically**. The user opens it through the
  task ring/badge, tray, or explicit command.
- WeatherFlow is silent by default. Human-state changes alter micro-weather but
  do not create speech bubbles, system notifications, or proactive actions.

### 2.3 State perception and privacy

- Human state uses a two-layer model:
  - an internal multi-dimensional state with evidence, trends, and uncertainty;
  - a stable weather projection consumed by the desktop shell.
- v3.0 may use:
  - deliberate signals: conversation, check-ins, task behavior, Calendar,
    GitHub, and user corrections;
  - consented device metadata: active/idle periods, application category
    switches, and continuity of work sessions.
- v3.0 must not collect:
  - keystroke content;
  - window or document contents through ambient sensing;
  - continuous screenshots;
  - clipboard history;
  - always-on microphone data.

### 2.4 Autonomy

- The default profile is **risk-based supervised autonomy**.
- Reads, scoped workspace writes, ordinary local commands, builds, and tests may
  run without per-action approval when they stay inside the run's authorized
  workspace and sandbox.
- External writes, account mutations, installations, destructive actions, and
  out-of-scope access require approval or are denied.
- A Skill can teach a method but can never grant authority.
- A third-party MCP server's annotations are descriptive, not trusted policy.

### 2.5 Rewrite and runtime strategy

- v3 is a full rewrite in the existing WeatherFlow repository.
- The core remains Python. Rust is used only where Tauri requires native shell
  or OS bridge code.
- Old code is not reused merely to preserve investment.
- v3 does not read or migrate v2 user data.
- Tauri is the flagship client, while the Python core remains independently
  usable through local HTTP/WebSocket, CLI, and MCP.
- v3.0 officially supports macOS only. Platform adapters must prevent needless
  lock-in, but Windows/Linux product support is deferred.

## 3. Goals and non-goals

### 3.1 Goals

- Make delegation feel easier than opening a full chat application.
- Make human state materially change how work is planned and delivered.
- Provide durable, inspectable, cancellable, resumable general-agent runs.
- Support bounded multi-agent delegation without recursive agent networks.
- Keep tool visibility and execution authority deterministic and auditable.
- Produce user-owned artifacts with source and run provenance.
- Allow capabilities to expand through built-ins, Skills, MCP, and Agent
  Definitions without expanding the trusted core.
- Preserve local ownership, deletion, export, and privacy controls.

### 3.2 Non-goals for v3.0

- Windows or Linux production support.
- Mobile clients, cloud synchronization, accounts, or team collaboration.
- Screen-content monitoring, keystroke logging, or ambient audio analysis.
- Recursive agent hierarchies, model councils, or arbitrary agent networks.
- A visual workflow editor, BPMN runtime, or a second workflow engine.
- A broad email/messaging integration marketplace.
- Backward compatibility with WeatherFlow v2.

## 4. Flagship acceptance story

The end-to-end design is anchored by this request:

> I am already overloaded, but this version still has to ship. Help me complete
> the release preparation with the least additional burden.

The expected behavior is:

1. The current HumanStateSnapshot indicates high cognitive load and recovery
   need, with sufficient evidence and freshness.
2. The user submits the request through the pure input capsule.
3. The capsule closes. A durable Run is created, and the companion task ring
   indicates background work.
4. The Orchestrator receives a RhythmPolicy that favors fewer questions,
   batched approvals, background delegation, compact output, and removal of
   non-critical scope.
5. Leaf Workers inspect the repository, research release requirements, run
   checks, and assemble artifacts.
6. Scoped local edits and tests execute autonomously in the sandbox.
7. Push, release creation, or Calendar mutations pause the Run in
   WAITING_APPROVAL.
8. The ring becomes amber, but no window opens automatically.
9. The user opens the Cockpit, reviews a structured action preview, and decides.
10. The Run resumes from its checkpoint and completes without duplicating prior
    side effects.
11. Release artifacts are committed atomically with source and Run provenance.
12. Task behavior is appended as new rhythm evidence, without changing history.

Passing this story requires the desktop, harness, trust, rhythm, memory,
artifact, and recovery contracts to work together.

## 5. Top-level architecture

```text
Tauri Desktop Shell
  - Floating Companion
  - Command Capsule
  - Cockpit
  - Native Bridge
           |
           | local HTTP + WebSocket, per-launch authentication
           v
Python Harness Daemon
  - Run Coordinator
  - Agent Runtime
  - Capability Plane
  - Trust Plane
  - Background Runtime
           |
           +---------------------------+
           |                           |
           v                           v
Rhythm Intelligence              Capability Packs
  - Signal ingestion               - Developer
  - Feature aggregation            - Research
  - State estimator                - Personal Operations
  - RhythmPolicy                   - Installed/custom
  - Weather projection
           |                           |
           +-------------+-------------+
                         v
Local Data Plane
  - Operational SQLite state
  - Append-only event/signal ledger
  - Memory and derived semantic index
  - Managed artifact files
```

### 5.1 Boundary rules

- Tauri does not infer human state, classify tool risk, or run agent business
  logic.
- The daemon is the only writer of WeatherFlow operational state.
- Rhythm Intelligence is a daemon domain with explicit interfaces, not a
  special system prompt fragment.
- Capability Packs depend on public harness contracts; the harness core does
  not depend on pack internals.
- Storage is accessed through repository interfaces. Domains do not open
  ad-hoc database connections.

## 6. Python Harness Core

### 6.1 Run Coordinator

The core uses a small, deterministic, persisted Run Coordinator rather than a
fixed chat graph or a general workflow engine.

Every command creates a Run, including quick answers. A Run may complete after
one model call or may expand into a durable multi-step task; the storage and
event contract is the same.

Required Run fields include:

```text
run_id
client_request_id
user_intent
workspace_id
status
version
created_at / updated_at
rhythm_snapshot_id
capability_snapshot_id
policy_profile
budget
checkpoint_ref
result_summary
error_class / error_message
```

`client_request_id` provides idempotency for desktop, CLI, and MCP retries.

### 6.2 Run state machine

Allowed statuses are:

```text
QUEUED
PLANNING
RUNNING
WAITING_APPROVAL
WAITING_USER
PAUSED
NEEDS_REVIEW
SUCCEEDED
FAILED
CANCELLED
```

Key transitions:

- `QUEUED -> PLANNING -> RUNNING`
- `RUNNING <-> WAITING_APPROVAL`
- `RUNNING <-> WAITING_USER`
- `RUNNING -> PAUSED` for recoverable provider/resource exhaustion
- any non-terminal state may become `CANCELLED`
- a known unsuccessful terminal outcome becomes `FAILED`
- uncertain side-effect state becomes `NEEDS_REVIEW`, never an automatic retry
- only a committed result and artifact set may become `SUCCEEDED`

The coordinator owns transitions. Model output cannot directly assign status.

### 6.3 Shared agent turn loop

Orchestrator and Workers use the same turn loop:

1. Load the persisted checkpoint.
2. Assemble context for the agent definition.
3. Call the selected model.
4. Parse structured text/tool/delegation output.
5. Apply deterministic tool visibility and policy checks.
6. Execute, request approval, delegate, or return an error observation.
7. Normalize and size-bound the observation.
8. Persist transcript delta, usage, events, and checkpoint.
9. Evaluate stop conditions.
10. Continue or return a structured result.

The loop must support provider adapters without embedding provider-specific
message structures into domain data.

#### 6.3.1 Production model adapter

MiniMax's OpenAI-compatible Chat Completions API is the first production model
provider, with `MiniMax-M3` as the default. `MiniMaxAdapter` translates domain messages, frozen `ToolSpec`
schemas, usage, final text, tool calls, and bounded leaf delegation at the
provider boundary. Canonical dotted tool IDs receive deterministic provider-
safe aliases and map back before the runtime sees a `ModelTurn`; an unknown
alias fails closed.

Per-Workspace SQLite configuration owns only provider, model, HTTPS base URL,
version, and `credential_ref`. The MiniMax API key lives in macOS Keychain and
is resolved by `CredentialBroker` only inside the HTTP transport callback.
Echo is a visible unconfigured smoke fallback, not a production model path.

MiniMax reasoning fields and `<think>` blocks are not persisted in domain
messages, checkpoints, events, or memory. M3 requests explicitly set
`thinking.type=disabled`, so multi-turn tool continuity does not require replay
of hidden reasoning. WeatherFlow preserves action/tool continuity rather than
hidden chain-of-thought. Provider errors are redacted and enter the existing
bounded retry/pause semantics.

### 6.4 Agent hierarchy

- One Orchestrator owns the user goal, decomposition, delegation, and final
  result.
- Workers are leaf agents and cannot spawn more agents.
- Default maximum Worker concurrency is three.
- Worker results returned to the parent are compact structured results and
  artifact references, not complete private transcripts.
- Agent Definitions control prompt sections, model hints, tool filters, skill
  filters, and budgets. They cannot widen the parent's authority.
- RhythmPolicy may reduce user interaction or change decomposition behavior,
  but it does not bypass Run budgets or Trust Plane decisions.

### 6.5 Checkpointing and side effects

- Persist after every model turn.
- Persist a proposed side effect before requesting approval.
- Give every side-effecting tool call an `action_id` and idempotency metadata.
- Persist the execution result before advancing the Run.
- If process death occurs between external execution and result persistence,
  mark the Run `NEEDS_REVIEW` unless the tool has a verified idempotent status
  check.
- Approval timeout suspends the Run; it does not fail or execute the action.

## 7. Rhythm Intelligence

### 7.1 Pipeline

```text
Raw Signals
  -> deterministic feature extraction
  -> textual signal interpretation where needed
  -> evidence-aware fusion
  -> HumanStateSnapshot
  -> RhythmPolicy + WeatherPresentation
```

Raw facts and user corrections are append-only events within their retention
policy. HumanStateSnapshot, RhythmPolicy, and WeatherPresentation are derived.

### 7.2 Internal state dimensions

Each snapshot contains six independent normalized dimensions. Each dimension
has a value, confidence, trend, supporting evidence, contradicting evidence,
and freshness.

| Dimension | Meaning |
|---|---|
| `energy` | Subjective energy and recovery indications |
| `cognitive_load` | Simultaneous commitments and processing pressure |
| `fragmentation` | Switching density and interruption of continuous work |
| `momentum` | Progress, completion, and stagnation trend |
| `friction` | Blocking, uncertainty, and repeated failure |
| `recovery_need` | Need for recovery after sustained load |

An internal numeric value is an estimate, not a diagnosis. Low coverage,
conflicting evidence, or expired evidence lowers confidence. The UI must not
present these values as medical or objective measurements.

### 7.3 HumanStateSnapshot contract

```text
snapshot_id
observed_at
window_start / window_end
dimensions: map[dimension, DimensionEstimate]
summary
supporting_event_ids
contradicting_event_ids
freshness
valid_until
estimator_version
```

User correction creates a new high-weight signal and triggers recomputation. It
does not edit the previous snapshot.

### 7.4 RhythmPolicy

The harness consumes behavior-oriented policy, not weather names.

Required fields:

```text
interaction_budget
response_density
delegation_bias
scope_pressure
work_mode: single_thread | normal | diagnostic
proactivity: silent
reason_refs
valid_until
```

Examples:

- Overload: minimize questions, batch approvals, favor background delegation,
  compress output, and suggest removal of non-critical work.
- Fragmented: maintain one user-visible thread, preserve context summaries, and
  avoid introducing parallel topics.
- Blocked: favor diagnostic/research work and explicit unblock options.
- Flow: protect the active objective and avoid unnecessary interaction.
- Recovery: avoid scope expansion and prefer deferred, reversible work.

Explicit user goals remain authoritative. RhythmPolicy may change execution
strategy and recommend scope changes, but it cannot silently refuse or rewrite
the goal.

### 7.5 WeatherPresentation

The backend projects snapshots into this stable vocabulary:

| Scene | Meaning |
|---|---|
| `clear` | Flow |
| `fair` | Steady |
| `fog` | Fragmented |
| `storm` | Overload |
| `still` | Blocked |
| `night` | Recovery |
| `mixed` | Unknown, contradictory, or insufficient evidence |

Payload fields include:

```text
scene
intensity
transition
snapshot_id
valid_until
presentation_version
```

The shell maps presentation tokens to packaged animation assets. It does not
contain human-state-to-weather logic.

## 8. Tauri Desktop Shell

### 8.1 Window model

1. **Companion Window**
   - transparent, borderless, movable, optionally always-on-top;
   - micro-weather for human state;
   - outer ring/badge for Run state;
   - never produces proactive text.
2. **Command Capsule**
   - anchored to the companion;
   - opened by character click or global shortcut;
   - one focused input with paste and file drop;
   - closes immediately after successful command acceptance.
3. **Cockpit Window**
   - normal application window;
   - tasks, approvals, artifacts, run timeline, evidence, settings, diagnostics;
   - opens only through explicit user action.

### 8.2 Run presentation states

| Run state | Companion treatment |
|---|---|
| idle | no task ring |
| queued/running | animated cyan/indigo ring |
| waiting approval | amber ring and small approval badge |
| paused/offline | muted gray ring |
| succeeded | short green completion transition, then idle |
| failed/needs review | red or coral badge; no modal or auto-open |

Human-state weather remains visible through every Run state.

### 8.3 Native Bridge responsibilities

- tray and application lifecycle;
- global shortcut;
- companion positioning and display changes;
- start/attach/health/restart management for the Python daemon;
- macOS activity/idle/application-category metadata adapter;
- autostart and background-run preferences;
- reduced-motion, particles, contrast, and always-on-top settings.

The activity adapter emits metadata only. No raw content is passed to the
daemon.

### 8.4 Daemon bridge

- Bind only to loopback on a random available port.
- Authenticate every request with a per-launch random token handed to Tauri in
  memory.
- Use HTTP for commands and snapshots.
- Use WebSocket for ordered typed events.
- WebSocket reconnect includes an event cursor; if the cursor is no longer
  available, fetch current snapshots before resuming.
- If the daemon is unavailable, show neutral weather and an offline ring.
- Tauri may restart the daemon with bounded exponential backoff.
- Closing the main window does not imply daemon shutdown; the user's background
  preference controls it.

### 8.5 Initial local API surface

The implementation must provide equivalent operations, even if exact routing
syntax changes during the implementation plan:

```text
POST /v1/runs
GET  /v1/runs/{run_id}
POST /v1/runs/{run_id}/cancel
GET  /v1/runs/{run_id}/timeline
GET  /v1/approvals
POST /v1/approvals/{approval_id}/decision
GET  /v1/artifacts/{artifact_id}
GET  /v1/rhythm/current
GET  /v1/desktop/snapshot
WS   /v1/events?cursor={event_id}
```

## 9. Capability Plane and Trust Plane

### 9.1 Capability sources

- built-in tools;
- connected MCP tools;
- Skills;
- Agent Definitions;
- first-party and installed Capability Packs.

### 9.2 ToolSpec

Every tool is normalized to a canonical contract:

```text
tool_id
description
input_schema / output_schema
effect
required_scopes
idempotency
timeout
source
source_version
health
```

Effects are:

```text
observe
workspace_write
execute
network_read
external_write
install
destructive
sensitive
```

### 9.3 Per-Run capability resolution

At Run creation/planning time:

1. Match explicit mentions and relevant Capability Packs/Skills.
2. Select the smallest plausible tool surface.
3. Apply the Agent Definition's tool and skill filters.
4. Apply Workspace scopes and policy visibility.
5. Freeze a versioned `RunCapabilitySnapshot`.

Runs do not hot-switch tool schemas. Registry updates affect new Runs only.

### 9.4 Workspace contract

A Workspace owns:

- action roots;
- WeatherFlow internal root, inaccessible to ordinary agent tools;
- artifact root;
- connector account/repository/calendar scopes;
- network policy;
- installed packs and agent definitions;
- default budgets;
- active session grants.

A Workspace is an authority boundary, not merely a working directory.

### 9.5 Default supervised policy

| Effect | Default | Constraints |
|---|---|---|
| observe | allow | authorized scopes only; sensitive fields brokered/redacted |
| workspace_write | sandbox | authorized roots; diff and recovery metadata |
| execute | sandbox | command classification, path/time/resource limits |
| network_read | allow | declared network tools; source recorded |
| external_write | approve | structured preview; approval may batch planned actions |
| install | approve | never silent; bounded source and destination |
| destructive | approve | never permanently allowed; preview required |
| out-of-scope/unknown | deny or hide | fail closed |

The execution layer repeats policy checks even if the model never saw the tool.

### 9.6 Credentials

- The model never receives raw credentials.
- A Credential Broker resolves `credential_ref` and signs/injects requests at
  the transport boundary.
- Logs, events, checkpoints, memory, and artifact manifests store references or
  redacted summaries only.

## 10. Data, memory, and provenance

### 10.1 Operational state

SQLite transaction tables own current mutable state:

- tasks, runs, and steps;
- approvals and action results;
- agent runs and lineage;
- workspaces, scopes, and grants;
- checkpoints and cursors;
- artifact metadata;
- current derived snapshot cache.

Rows use versioning/optimistic concurrency where competing updates are
possible. SQLite runs in WAL mode. Domain repositories own queries and
transactions.

### 10.2 Event and signal ledger

Audit and signal facts are append-only within retention policy.

The envelope is:

```text
event_id: ULID
type
recorded_at: UTC
actor: user | agent | system
stream: {kind, id}
correlation_id
causation_id
payload: typed JSON
sensitivity: normal | private | secret_ref
retention_class: audit | signal_raw | signal_aggregate
```

User privacy deletion and retention expiration are explicit exceptions to
append-only storage. Append-only is an audit property, not a reason to deny
data deletion.

### 10.3 Memory roles

1. **Working Context**
   - assembled per model call;
   - includes current Run, recent conversation, capability snapshot,
     HumanStateSnapshot, and relevant memory;
   - no independently persisted duplicate.
2. **Episodic Memory**
   - selectively stores future-useful task experiences, preferences, and
     outcomes;
   - every entry links to real source event IDs.
3. **Profile Assertions**
   - structured, user-editable long-term claims;
   - fields include claim, confidence, status, evidence, created_at,
     last_confirmed_at, and origin.
4. **Semantic Index**
   - derived from episodic memory and active profile assertions;
   - deletable and rebuildable;
   - never a truth source.

### 10.4 Artifact Store

- Artifact bytes live in managed files, not large SQLite payloads.
- Each artifact has a manifest with type, version, checksum, creator Run,
  source references, and validation status.
- Writes use a temporary path and atomic rename after validation.
- Failed Runs may expose validated partial artifacts with an explicit partial
  status.
- Users can open, export, copy, or delete artifacts.

### 10.5 Retention defaults

- Raw application-switch/active/idle events: 72 hours.
- Aggregated behavior features: 90 days.
- User-authored conversations, task history, approved audit records, memory, and
  artifacts persist until user deletion or workspace policy expiration.
- Users may independently reset behavior history, episodic memory, profile
  assertions, artifacts, or an entire Workspace.

## 11. Built-in Capability Packs

### 11.1 Developer Pack

- scoped filesystem read/write;
- sandboxed shell;
- Git local operations;
- GitHub read and approved external-write operations;
- build/test execution;
- patch, release checklist, and validation artifacts.

### 11.2 Research Pack

- web and source retrieval;
- provenance-aware notes;
- parallel research Workers;
- source validation;
- report and bibliography artifacts.

### 11.3 Personal Operations Pack

- Calendar read/write;
- local task planning;
- meeting preparation;
- schedule proposals influenced by RhythmPolicy;
- all external mutations through approval.

Email and broad messaging integrations are deferred beyond v3.0. They must be
added as Packs/MCP capabilities, not core domains.

## 12. Reliability and failure semantics

| Failure | Required behavior |
|---|---|
| model timeout/rate limit | bounded exponential retry; pause after exhaustion; never fabricate success |
| optional tool/MCP unavailable | re-plan without it and record degraded capability |
| required tool/MCP unavailable | checkpoint and fail/pause with a user-actionable reason |
| daemon crash | Tauri restarts with backoff; daemon scans non-terminal Runs |
| Tauri crash/exit | daemon continues according to preference; reconnect by event cursor |
| uncertain external side effect | mark `NEEDS_REVIEW`; never blindly repeat |
| behavior sensor unavailable | continue with deliberate signals; lower state confidence |
| checkpoint corruption | isolate record, retain audit/artifacts, mark `NEEDS_REVIEW` |
| event cursor expired | refetch snapshots, then resume live events |
| capability schema drift | current Run retains frozen snapshot; new Run receives new schema |

Error messages shown to the user explain impact and available recovery actions,
not internal stack traces.

## 13. Observability

### 13.1 Local structured telemetry

Every log and trace event that belongs to a Run carries:

```text
run_id
trace_id
agent_run_id
tool_id/action_id when applicable
workspace_id
```

Logs redact secret markers and sensitive arguments.

### 13.2 Run Timeline

The Cockpit exposes a user-readable timeline of:

- plan and re-plan boundaries;
- Worker lifecycle;
- tool calls and summarized results;
- approvals and decisions;
- retries and degraded modes;
- artifacts and validation;
- terminal status.

Private chain-of-thought is never stored or shown. The timeline uses concise
execution summaries and structured events.

### 13.3 Diagnostics and telemetry

- Diagnostics are local by default.
- Users may explicitly export a redacted diagnostic bundle.
- v3.0 does not upload product telemetry by default.
- Metrics include latency, tool success, recovery count, token/cost usage,
  approval count, and user-interruption count.

## 14. Verification strategy

### 14.1 Unit and property tests

- Run state-machine transitions and forbidden transitions;
- policy classification and scope resolution;
- path/network/credential redaction;
- HumanStateSnapshot fusion and stale/unknown behavior;
- weather projection and RhythmPolicy generation;
- schema normalization and capability freezing;
- idempotency and event-causation invariants.

### 14.2 Integration tests

- SQLite transactions, WAL behavior, migrations, and crash recovery;
- Run resume across daemon restart;
- approval park/decide/resume;
- sandbox and command classification;
- MCP discovery, disconnect, and schema drift;
- artifact atomic commit and partial failure;
- behavior metadata ingestion and retention expiration;
- HTTP/WebSocket authentication and cursor replay.

### 14.3 Agent trajectory evaluations

Use deterministic fixture tools and recorded results. Evaluate:

- whether the Orchestrator selected minimal capabilities;
- whether the plan responded to RhythmPolicy without changing the goal;
- whether Workers remained leaf agents;
- whether external writes stopped for approval;
- whether sources and artifacts retained provenance;
- whether failure paths avoided false success.

LLM judges may score qualitative planning and usefulness. Deterministic code
must judge policy, state transition, provenance, and recovery contracts.

### 14.4 macOS Tauri E2E

- launch/attach daemon;
- click and global-shortcut capsule activation;
- submit and immediate capsule collapse;
- weather update without a proactive bubble;
- task ring state transitions;
- explicit Cockpit opening;
- approval through Cockpit;
- daemon crash and recovery;
- Tauri restart and event/snapshot recovery;
- reduced-motion and sensor-permission fallback.

### 14.5 Security and privacy checks

- path traversal and symlink escape;
- loopback authentication;
- unknown tool denial;
- credential leakage scans across logs/events/checkpoints/memory;
- forbidden raw sensor-content checks;
- retention expiry;
- external-write approval invariant.

## 15. Performance and safety acceptance targets

- Command capsule opens within 100 ms on supported macOS hardware after app
  readiness.
- The daemon accepts and acknowledges a local command within 300 ms, excluding
  model latency.
- After daemon failure, Tauri begins recovery within 5 seconds.
- WebSocket reconnect does not silently lose final Run state.
- There are zero unapproved `external_write`, `install`, or `destructive`
  actions under the supervised profile.
- Duplicate `client_request_id` or `action_id` never causes duplicate execution.
- Low-confidence or expired human state projects to `mixed` rather than a false
  precise weather state.

## 16. Delivery phases

### P0: Contract and clean skeleton

- tag/archive the current v2 state;
- create `weatherflow-architecture-v3.md`, update `AGENTS.md`, and explicitly
  supersede v2 for all subsequent implementation work;
- make this approved design and the v3 architecture document mutually
  consistent before changing runtime code;
- establish new repository layout, package boundaries, schemas, and test gates;
- do not carry forward old runtime code or data compatibility.

### P1: Headless Python Core

- Operational Store and Event Ledger;
- Run Coordinator and shared turn loop;
- Workspace, Capability Resolver, ToolSpec, Trust Plane, Approval;
- Artifact Store;
- CLI-driven durable Run with crash recovery.

### P2: Desktop and Rhythm

- Tauri Companion, Capsule, and Cockpit;
- daemon supervisor and authenticated bridge;
- macOS activity metadata adapter;
- HumanStateSnapshot, RhythmPolicy, WeatherPresentation;
- micro-weather and Run ring.

### P3: Flagship vertical slice

- Developer, Research, and Calendar capabilities required by the flagship
  release story;
- bounded Worker delegation;
- structured approvals and artifact validation;
- trajectory eval and macOS E2E for the complete story.

### P4: Generalization and v3.0 hardening

- Capability Pack packaging;
- Skill and Agent Definition installation;
- MCP client and server surfaces;
- Personal Operations completion;
- diagnostics, retention controls, onboarding, signing, packaging, and release
  validation.

Each phase must end in a runnable, verified increment. No phase may add a second
execution path to bypass the Run Coordinator.

## 17. Architecture invariants

1. Python Harness Daemon is the sole business core.
2. Tauri never infers human state or tool risk.
3. Explicit user goals outrank rhythm-derived strategy recommendations.
4. Human state weather and Agent work state use separate visual channels.
5. Cockpit never auto-opens.
6. v3.0 proactivity is silent ambient presentation only.
7. Workers are leaf agents.
8. Model output cannot mutate Run state or bypass Trust Plane decisions.
9. Skills and MCP annotations cannot grant authority.
10. Credentials never enter model-visible or durable diagnostic data.
11. Semantic indexes are derived and rebuildable.
12. Operational state, audit events, memory, and artifacts have distinct owners.
13. Unknown or out-of-scope capabilities fail closed.
14. Uncertain side effects enter `NEEDS_REVIEW`, not automatic retry.
15. User deletion and retention policy outrank append-only storage.
16. No v2 compatibility path exists in v3.
17. Model providers cannot widen frozen capabilities or persist hidden
    reasoning; credentials resolve only at their transport boundary.

## 18. Design completion criteria

This design is complete when an implementation plan can decompose P0-P4 without
making new product-level choices about identity, autonomy, privacy, desktop
behavior, state semantics, storage ownership, or v3.0 scope.

Concrete Python libraries, provider SDK adapters, Tauri UI framework choices,
animation assets, and detailed module filenames are implementation-plan
decisions. They must preserve the contracts and invariants in this document and
must not introduce an alternative execution or authority path.
