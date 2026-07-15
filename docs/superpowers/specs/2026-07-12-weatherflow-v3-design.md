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
2. **The desktop weather glyph is the primary habit surface.** A quiet floating
   icon communicates human state through a stable weather symbol and accepts commands
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
  - a floating weather glyph for ambient presence and fast input;
  - a full Cockpit for tasks, approvals, artifacts, history, and settings.
- Human state is rendered as one **simple weather icon** centered inside a
  compact fixed square tile, without a mascot, orbit, or particle system. The
  native window fits the visible tile closely rather than adding a broad
  transparent hit region.
- Agent work state is rendered separately through one small status dot. Agent
  state never replaces human-state weather.
- The whole weather icon distinguishes click from drag: pointer movement beyond
  a small threshold invokes native window dragging; a click or global shortcut opens a **pure input
  capsule**. The capsule contains no recommendations, history, rhythm summary,
  or task timeline.
- Submitting a command immediately closes the capsule. Escape, the explicit
  close control, and loss of window focus also close it.
- The Cockpit **never opens automatically**. The user opens it through the
  task status dot, tray, or explicit command.
- WeatherFlow is silent by default. Human-state changes alter micro-weather but
  do not create speech bubbles, system notifications, or proactive actions.
- Inside the explicitly opened Cockpit, conversation is the dominant workspace.
  A persistent navigation rail leads to conversation, Runs, rhythm,
  integrations, and settings; these are dedicated views rather than a dense
  equal-weight dashboard card grid.

### 2.3 State perception and privacy

- Human state uses a two-layer model:
  - an internal multi-dimensional state with evidence, trends, and uncertainty;
  - a stable weather projection consumed by the desktop shell.
- v3.0 may use:
  - deliberate signals: conversation, check-ins, task behavior, Calendar,
    GitHub, bounded Gmail metadata, and user corrections;
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
- A broad email/messaging integration marketplace. Gmail is the only bounded
  first-party email connector in v3.0.
- Backward compatibility with WeatherFlow v2.

## 4. Flagship acceptance story

The end-to-end design is anchored by this request:

> I am already overloaded, but this version still has to ship. Help me complete
> the release preparation with the least additional burden.

The expected behavior is:

1. The current HumanStateSnapshot indicates high cognitive load and recovery
   need, with sufficient evidence and freshness.
2. The user submits the request through the pure input capsule.
3. The capsule closes. A durable Run is created, and the secondary task dot
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

### 4.1 Product-loop reset acceptance

Before further provider or packaging expansion, the implementation must pass a
smaller live trajectory using the Developer Pack and MiniMax-M3:

1. The user explicitly authorizes an existing project directory as a Workspace.
2. Capsule submission durably creates a Run and returns before model latency.
3. The daemon owns background execution through `SharedTurnLoop`; no client
   process or alternate task runner owns the work.
4. Companion reflects queued/running/approval/terminal state from committed
   Run facts.
5. Cockpit lists recent Runs and exposes the selected Run's final result,
   summarized timeline, approvals, and authenticated Artifact content.
6. A deliberate state check-in or correction affects the selected Workspace;
   native activity metadata is ingested only after persisted opt-in.
7. A real read-only MiniMax-M3 run inspects the authorized repository and
   completes without modifying it.

Calendar, GitHub, Research, MCP discovery, extension marketplace UX, release
packaging, and advanced memory automation are not acceptance dependencies for
this reset.

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
session_id (optional)
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

`client_request_id` provides idempotency for desktop, CLI, and MCP retries. Its
first accepted Run binds the key to that Run's Workspace and optional
conversation session. A retry with a different Workspace or session is a typed
conflict and must never return the pre-existing Run.

#### 6.1.1 Conversation sessions

The Cockpit groups related Runs in durable, Workspace-scoped conversation
sessions. A session has a user-editable title, a pin flag, timestamps, and a
derived latest Run reference. Sessions may be created before their first Run.
New Runs may reference one session; Runs created before this contract or from
non-conversation clients may keep a null session reference and remain fully
accessible.

Creating or attaching a Run moves its session to the top of the recent list.
Pinned sessions sort before unpinned sessions. Rename and pin operations affect
only presentation metadata: they cannot change Run state, frozen model or
connector routes, capability snapshots, Trust decisions, or Workspace scopes.
Every mutation carries the owning `workspace_id`; a mismatched identity is
reported as not found. Listing Runs by `session_id` likewise requires and
validates the owning `workspace_id` before returning any rows.

Deleting a session is an explicit privacy deletion rather than a presentation
detach. The request carries the owning `workspace_id` and a mismatch fails
closed as not found. The daemon first stops its known background tasks for the
session, then one SQLite transaction removes the session, its Runs, Actions,
Approvals, checkpoints/quarantine, frozen capability/model/connector routes,
provider continuations, artifact manifests, and the full causal event subtrees
owned by those Runs. Content-addressed artifact bytes are removed after commit
only when no surviving Run in the same Workspace still references the digest.
No deletion-completed event may retain the deleted session or Run identity.

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

#### 6.3.1 Production model adapters

MiniMax's OpenAI-compatible Chat Completions API remains the default production
provider, with `MiniMax-M3` as the default model. The curated production set is
MiniMax, DeepSeek, Moonshot/Kimi, Alibaba Model Studio/Qwen, Zhipu GLM,
SiliconFlow, StepFun, OpenAI, and Anthropic. OpenAI uses its first-party
Responses API with server-side response storage disabled; Anthropic uses its
first-party versioned Messages API. Provider adapters translate domain
messages, frozen `ToolSpec` schemas, usage, final text, tool calls, and bounded
leaf delegation at the provider boundary. Canonical dotted tool IDs receive
deterministic provider-safe aliases and map back before the runtime sees a
`ModelTurn`; an unknown alias fails closed.

Per-Workspace SQLite configuration owns only provider, model, HTTPS base URL,
version, and `credential_ref`. The MiniMax API key lives in macOS Keychain and
is resolved by `CredentialBroker` only inside the HTTP transport callback.
Echo is a visible unconfigured smoke fallback, not a production model path.

All provider API keys live in macOS Keychain. Provider presets expose model and
HTTPS API endpoint in Cockpit. The primary desktop flow uses the fixed official
endpoint, while the typed core contract retains deliberate override support for
compatible regional or Workspace endpoints. Endpoint customization never
widens tools, scopes, or authority. The renderer can set, delete, and inspect
presence for a provider key but cannot read it back.

OpenAI and Anthropic maintained-model suggestions are intersected with the
credential-scoped first-party Models API before selection, as for the existing
curated providers. OpenAI Responses requests replay exact response output items
needed by a later function-call turn. Anthropic Messages requests replay the
exact assistant content blocks needed by a later `tool_result`, including any
provider signature. Those opaque wire records use the same encrypted,
retention-bounded provider-continuation owner described below and never enter
the normalized transcript, prompt text, events, logs, memory, or artifacts.

Model-cost accounting is based on provider-reported token usage and an exact,
versioned price entry for the frozen provider, model, and billing origin. The
MiniMax catalog version `minimax-paygo-2026-07-14` records the official global
pay-as-you-go equivalent for maintained M3 and M2.x models. It intentionally
does not assume cache discounts, subscription-plan allocation, or a custom
OpenAI-compatible endpoint, so the estimate remains conservative and
auditable rather than pretending to reproduce an account invoice.

If a Run has a finite `max_cost_usd`, unknown model pricing, a custom billing
origin, or missing provider usage is an `UNKNOWN` cost state rather than zero.
After the provider turn that reveals this state, SharedTurnLoop fails closed
before dispatching tools or committing a terminal result. Checkpoints retain
the pricing-catalog version and whether cumulative cost is known.

One provider key may expose multiple language models. WeatherFlow intersects
first-party providers' official maintained allowlists with the models actually
available to that credential; SiliconFlow uses its credential-scoped live text
catalog. Exactly one provider/model pair is active per Workspace. The user may
switch it from the conversation composer or Settings, and the new selection
applies to subsequent Runs. v3 does not perform automatic model routing.

At Run acceptance, WeatherFlow copies the Workspace selection into an immutable
`run_model_routes` record containing provider, model, endpoint, credential
reference, and configuration version, but never credential material. The
SharedTurnLoop resolves its adapter from this Run-scoped record once per resume;
it does not own a mutable process-global provider. Worker Runs inherit the
parent Run route. A later Workspace switch cannot change an accepted or active
Run. Missing frozen route data fails closed to `NEEDS_REVIEW`.

The route emits `model.route_bound` with provider, model, and configuration
version for local audit. The adapter also supplies that same provider/model pair
as trusted system metadata, allowing the assistant to answer model-identity
questions from the actual runtime route rather than unreliable pretrained
self-identification.

Provider reasoning fields and `<think>` blocks are not persisted in domain
messages, checkpoints, events, memory, artifacts, diagnostics, or timeline
events. M3 requests explicitly set `thinking.type=disabled`. MiniMax M2.7,
M2.5, M2.1, M2 and their maintained high-speed variants remain selectable by
using the independent provider-continuation boundary described below.

For an M2.x tool or delegation turn, the adapter returns the normalized
`ModelTurn` plus the complete provider assistant message required for protocol
replay. The SharedTurnLoop, not the adapter, persists that message in
`provider_continuations` in the same transaction as the checkpointed normalized
turn. Subsequent requests decrypt and inject the exact message at its original
assistant position. The domain transcript continues to contain only normalized
text/tool/delegation data.

Continuation records use AES-256-GCM with a fresh nonce and authenticated
Run/provider/model/step/schema/expiry metadata. Their installation encryption
key is generated by Tauri, stored in macOS Keychain, resolvable only through the
private native broker, and not addressable by renderer credential commands.
CLI-only operation may create the same fixed internal Keychain item through the
CLI credential adapter. The key never enters SQLite, process arguments, `.env`,
events, logs, memory, artifacts, diagnostics, or model input.

Each continuation is unique by `(run_id, step_index)`, defaults to a seven-day
expiry, and is deleted immediately when its Run succeeds, fails, or is
cancelled. Expired rows are removed eagerly on startup and access. A missing,
expired, corrupt, unauthenticated, or provider/model-mismatched continuation
required by a non-terminal Run moves that Run to `NEEDS_REVIEW`; WeatherFlow
never reconstructs or retries the provider turn without it.

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
- Only a Trust Policy `ALLOW` decision may execute without a durable Action.
  `SANDBOX` decisions, including workspace writes and command execution, first
  persist an Action and system authorization, then execute through the same
  ActionExecutionCoordinator used by approval-gated side effects. The effect
  and policy decision define this boundary; tool names do not.
- Give every side-effecting tool call an `action_id` and idempotency metadata.
  Provider call IDs are not assumed unique: the durable identity binds the Run,
  persisted model step, batch position, frozen tool, and canonical arguments.
  Reusing the same idempotency key for a different Run, tool, effect, or argument
  set fails closed.
- Persist the execution result before advancing the Run.
- If a recovered Action is already `SUCCEEDED` while its Observation is absent
  from the checkpoint, append the persisted Action result as that Observation
  and continue without invoking the executor again.
- If process death occurs between external execution and result persistence,
  mark the Run `NEEDS_REVIEW` unless the tool has a verified idempotent status
  check.
- If timeout or cancellation occurs after a sandboxed or approved executor has
  started, durably move both Action and Run to `NEEDS_REVIEW` before returning
  or propagating cancellation. Cancelling `asyncio.to_thread` only cancels its
  awaiter; it does not prove that the underlying thread or process stopped.
- Validate every executor result against the frozen `ToolSpec.output_schema`
  with JSON Schema Draft 2020-12 before constructing a Tool Observation. An
  empty schema explicitly accepts any object for compatibility. For `ALLOW`
  tools, a mismatch becomes a value-free `invalid_tool_output` Observation;
  the rejected value is absent from checkpoints, events, and model context.
- For `SANDBOX` and `APPROVE` tools, validate output while the Action is still
  `EXECUTING`. A mismatch moves Action and Run to `NEEDS_REVIEW` without
  persisting the returned value. Recovery revalidates any historical
  `SUCCEEDED` Action result before using it; an invalid result is cleared,
  enters `NEEDS_REVIEW`, and is never re-executed.
- Approval timeout suspends the Run; it does not fail or execute the action.

### 6.5.1 Durable Run controls

Live steering and follow-up are persisted as typed `run_controls`; they are not
process-local messages and they never interrupt a persisted tool or Action.
`steer` is consumed only when the checkpoint has no pending model turn, before
constructing the next `ModelRequest`. `follow_up` waits for a persisted
`FinalTurn`. At that boundary, SharedTurnLoop checks and applies every pending
control inside the same immediate database transaction that would otherwise
commit the Run result. A concurrent late control therefore either becomes part
of the next request or observes the already-terminal Run and is rejected.

Applying a control appends an ordinary User `AgentMessage`, clears the pending
final turn when necessary, advances the checkpoint version, marks the control
applied, and emits a value-free audit event in one transaction. Control content
does not enter Event payloads. Applied rows are never replayed after restart.
Runs in terminal or `NEEDS_REVIEW` state reject new controls; approval and
provider-continuation ownership remain unchanged.

### 6.6 OS sandbox execution boundary

`SANDBOX` decisions execute through a typed `SandboxBackend` owned by the Python
Harness. Trust decides whether an Action belongs on this path; the backend is
responsible for actually confining the process. Capability executors may prepare
an argv request but cannot launch an ordinary subprocess as a fallback.

The macOS v3 backend uses the host Seatbelt facility behind a replaceable
protocol. Its current launcher is `/usr/bin/sandbox-exec`, which is deprecated;
therefore runtime availability and a real escape-denial probe are release gates,
not optional diagnostics. If the facility disappears or the profile cannot be
compiled, command tools become unavailable and fail closed. A later native
launcher may replace it without changing Run, Action, ToolSpec, or checkpoint
contracts.

Every request freezes and validates:

```text
argv and working directory
readable roots and writable roots
reviewed read-only toolchain roots
offline or explicitly declared network mode
wall, CPU, file-size, file-descriptor, and output limits
the bounded non-secret environment
```

The profile begins with default deny. It exposes authorized Workspace roots,
an ephemeral per-execution HOME/temp root, required macOS runtime paths, and
reviewed toolchain roots only. Workspace writes never imply access to the
WeatherFlow internal root, Artifact Store, Keychain, provider sockets, or any
other user directory. External networking and signals to host processes are
denied by default. Explicit loopback mode admits loopback IP only; Unix sockets
are limited to the private HOME and authorized writable roots. A process may
signal its own children for normal build/test lifecycle management but cannot
signal the Harness or other host processes. Timeout and cancellation terminate
the process group and retain the existing durable `NEEDS_REVIEW` barrier for a
started side effect.

Build caches do not weaken credential isolation. The macOS backend constructs a
private offline `CARGO_HOME` and may link reviewed read-only registry and Git
caches into it, but it never exposes Cargo credentials or user config. Desktop
credential broker sockets use the process-private temporary root rather than a
hard-coded global `/tmp` path, so the Rust test/build lifecycle remains inside
the same sandbox boundary.

Daemon composition runs one cached escape-denial health probe before exposing
the backend. The probe executes a real sandboxed child and verifies that a file
outside its read and write roots remains inaccessible; missing launch files,
profile compilation failure, or an unexpected escape marks the backend
unhealthy. A daemon already running inside a WeatherFlow sandbox never attempts
to nest a weaker profile.

All descendants remain in the Harness-owned process group. The Seatbelt profile
denies `setsid` and `setpgid`, timeout/cancellation terminates the group, and a
fixed system resource launcher sets CPU, file-size, and descriptor limits
without Python `preexec_fn` or interpolation of project arguments. The current
Seatbelt entrypoint remains `/usr/bin/sandbox-exec`; replacing that deprecated
public launcher is a release gate, not a reason to fall back to an ordinary
subprocess.

Managed MCP processes use separate profiles from Developer commands. Approved,
version-pinned npm installation receives only the internal temporary install
root plus outbound HTTPS and ignores package scripts. The installed filesystem
stdio server is offline and read-only over its fixed installation and Workspace
roots. Backend absence marks it unavailable. Browser MCP remains unavailable
until WeatherFlow owns a redirect-safe public-network broker; an unrestricted
network profile is not an acceptable compatibility path.

The Developer Pack may admit direct Workspace executables and reviewed build/
test frontends only after this backend is available. Shell command strings,
package installation commands, Git remote mutations, and paths outside the
frozen Workspace remain denied or approval-gated. Build files may spawn child
processes, but every descendant inherits the same OS profile and limits.

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
   - one compact square tile containing micro-weather for human state;
   - outer ring/badge for Run state;
   - never produces proactive text.
2. **Command Capsule**
   - anchored to the companion;
   - opened by weather-icon click or global shortcut;
   - one focused input with paste and file drop;
   - closes immediately after successful command acceptance.
3. **Cockpit Window**
   - normal application window with persistent left navigation;
   - conversation-first primary view;
   - dedicated tasks, read-only status weather, approvals/artifacts,
     integrations, and settings views;
   - opens only through explicit user action.

The Cockpit left navigation keeps conversation, Runs, and status weather as the
primary product surfaces. A labeled Tools section contains Automations, Skills,
MCP Servers, LLM Models, and OAuth. Settings contains appearance, system, privacy, and
diagnostic preferences rather than duplicating those tool configuration pages.

Cockpit appearance is a shell-local preference, not Python domain state. The
user may choose `system`, `light`, or `dark`; the preference is stored under the
fixed `weatherflow.theme` key, applied before React renders, and `system` tracks
macOS appearance changes. Theme state never enters Runs, events, memory,
checkpoints, artifacts, prompts, or daemon configuration.

### 8.2 Status-weather presentation

- Status weather is a read-only personal-insight destination; it has no
  check-in, correction, composer, or other command-entry control.
- The current-state section shows WeatherPresentation, HumanStateSnapshot
  summary/dimensions, confidence, freshness, collaboration mode, and validity.
- Recent behavior shows only privacy-safe aggregate activity and task behavior.
  It never admits raw screen, window title, keystroke, clipboard, audio, or
  deliberate check-in text.
- Long-term profile shows active evidence-backed Profile Assertions with
  confidence, origin, evidence count, and update time. Empty states must not
  manufacture durable claims from a single current-state snapshot.
- Conversation and the Command Capsule remain the product's deliberate input
  surfaces. If deliberate state correction is added there, it requires an
  explicit typed backend contract; the status-weather page must stay read-only.

### 8.3 Run presentation states

| Run state | Companion treatment |
|---|---|
| idle | no task dot |
| queued/running | blue task dot |
| waiting approval | amber task dot |
| paused/offline | muted gray task dot |
| succeeded | return to idle |
| failed/needs review | red or coral task dot; no modal or auto-open |

Human-state weather remains visible through every Run state.

### 8.4 Native Bridge responsibilities

- tray and application lifecycle;
- global shortcut;
- companion positioning and display changes;
- start/attach/health/restart management for the Python daemon;
- macOS activity/idle/application-category metadata adapter;
- autostart and background-run preferences;
- reduced-motion, particles, contrast, and always-on-top settings.
- opening provider authorization URLs in the system browser; OAuth exchange,
  token storage, fetch policy, and connector state remain in Python.
- native Keychain mutation and presence checks for the fixed WeatherFlow
  credential-provider enum. Renderer code can set, delete, and read presence;
  it has no operation that returns secret material.

The activity adapter emits metadata only. No raw content is passed to the
daemon.

### 8.5 Daemon bridge

Local macOS development uses a fixed code requirement. `pnpm dev:app` must sign
the final Cargo debug executable after linking and before execution with the
identifier `ai.weatherflow.desktop.dev` and one stable local code-signing
certificate. A one-time setup command may create that self-signed certificate
in the login Keychain. Development must not fall back to an ad-hoc signature,
because its changing CDHash invalidates Keychain and TCC authorization after
each rebuild. This local identity is separate from release Developer ID signing
and notarization.

- Bind only to loopback on a random available port.
- Authenticate every request with a per-launch random token handed to Tauri in
  memory.
- The product renderer always resolves the native `daemon_bridge` command,
  including in development. A shell that cannot obtain the authenticated bridge
  fails closed; it never falls back to an unauthenticated endpoint. Isolated
  browser tests may inject an explicit bridge configuration, but there is no
  automatic browser fallback in product startup.
- Use HTTP for commands and snapshots.
- Use WebSocket for ordered typed events.
- Carry WebSocket authentication in a negotiated `Sec-WebSocket-Protocol`
  value, never in the URL query where access logs would record the launch token.
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
GET  /v1/runs
GET  /v1/runs/{run_id}
POST /v1/runs/{run_id}/cancel
GET  /v1/runs/{run_id}/timeline
GET  /v1/sessions
POST /v1/sessions
PATCH /v1/sessions/{session_id}
DELETE /v1/sessions/{session_id}
GET  /v1/approvals
POST /v1/approvals/{approval_id}/decision
GET  /v1/artifacts/{artifact_id}
GET  /v1/rhythm/current
GET  /v1/desktop/snapshot
GET  /v1/workspaces
POST /v1/workspaces
GET  /v1/automations
POST /v1/automations
PATCH /v1/automations/{automation_id}
POST /v1/automations/{automation_id}/run
GET  /v1/automations/{automation_id}/history
GET  /v1/skills/catalog
POST /v1/skills/{skill_id}/install
DELETE /v1/skills/{skill_id}
GET  /v1/mcp/catalog
POST /v1/mcp/{server_id}/install
POST /v1/mcp/{server_id}/enable
POST /v1/mcp/{server_id}/disable
WS   /v1/events?cursor={event_id}
```

### 8.6 Automations and tool administration

An Automation stores a name, prompt, Workspace, enabled/paused state, timezone,
schedule specification, next occurrence, and Run history. A scheduler may wake
an enabled Automation, but it can only submit the prompt as an ordinary durable
Run with a deterministic client request ID. The selected Workspace model and
capabilities are resolved and frozen when that Run is accepted. At startup, at
most one overdue occurrence is submitted per Automation; subsequent occurrences
advance from the schedule without catch-up floods.

Manual run, pause, resume, edit, and delete are explicit user operations. An
Automation never calls a tool directly, auto-opens Cockpit, produces proactive
text, or changes approval requirements. Its list/detail UI follows the normal
Cockpit navigation and exposes current state and linked Run history.

Skills and MCP Servers are administered per Workspace. Install and enable
controls show source, version, requested capabilities, and health. Renderer
clients send only fixed catalog identifiers and user-owned Workspace choices;
they never supply executable commands, arbitrary package URLs, secret values,
or authority annotations. An install request returns `needs_approval` after
persisting a dedicated Run, Action, and Approval. Only the later persisted user
decision may move that Action to execution; a `confirm` boolean or synthesized
authorization id has no authority. Unknown, expired, or cross-Workspace
decisions fail closed. Recovery never retries an approved or executing install:
an executing Action is moved to `NEEDS_REVIEW`, while an approved-but-not-started
Action waits for another explicit user decision.

## 9. Capability Plane and Trust Plane

### 9.1 Capability sources

- built-in tools;
- connected MCP tools;
- Skills;
- Agent Definitions;
- first-party and installed Capability Packs.

The initial Skill catalog is sourced from the local `wesley-skills` checkout.
WeatherFlow validates each selected package, copies it into the verified
content-addressed extension store, and records an immutable Workspace reference.
Installed Runs do not read the source checkout, and a catalog update never
changes an existing Run or installed snapshot implicitly.

The desktop MCP catalog is curated and version-pinned. Installation destinations
live under WeatherFlow's internal root. Presets define their executable and safe
arguments in Python; the renderer can select a preset and bounded Workspace
options only. Enabling a preset discovers and normalizes its tools for future
Runs. Disabling it closes the transport and removes it from future capability
resolution without mutating frozen Run snapshots. A healthy enabled preset
contributes its catalog-fixed `mcp:{preset}:use` scope only as an effective input
to that future snapshot resolution. It does not mutate durable Workspace grants,
and discovery metadata or MCP annotations cannot select or expand the scope.

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

1. Read the explicit Run tool mode. Missing input defaults to `ask`.
2. Build one candidate surface from installed Capability Packs, enabled MCP
   presets, and every active connector identity in the selected Workspace.
3. In `ask`, retain only `observe` and `network_read` ToolSpecs. In `bypass`,
   retain the complete reviewed candidate surface.
4. Apply the Agent Definition's tool and skill filters.
5. Apply Workspace scopes and policy visibility.
6. Freeze a versioned `RunCapabilitySnapshot` together with the Run's mode.

Runs do not hot-switch tool schemas or modes. Registry updates and a later
composer toggle affect new Runs only. `bypass` means bypassing the read-only
visibility filter, not bypassing Workspace boundaries, Trust, sandboxing,
Action persistence, or Approval.

### 9.4 Workspace contract

A Workspace owns:

- action roots;
- WeatherFlow internal root, inaccessible to ordinary agent tools;
- artifact root;
- connector account/repository/calendar scopes;
- network policy;
- installed packs and agent definitions;
- installed Skill snapshots and enabled MCP preset references;
- persisted Automations that target the Workspace;
- default budgets;
- durable conversation sessions, which are presentation groupings and do not
  own capability grants.

The first production connector slice is intentionally fixed to GitHub, Gmail,
and Google Calendar; later curated OAuth catalog entries follow the same
identity and credential-isolation contract without inheriting capability.
Connection requires explicit user action. Read-only automatic fetch may run
silently only for an entry whose backend definition explicitly supports it, at
a bounded interval chosen by the user. A connector binding owns only the active
account identity, reviewed OAuth scopes, and background-fetch settings. It does
not own a per-conversation tool grant. New Runs derive connector tools from the
Run's `ask` or `bypass` mode, and only toolkits with fixed reviewed WeatherFlow
ToolSpecs can contribute. Neither connection nor automatic fetch can authorize
external writes or widen an already-frozen Run. The former
`disabled`/`read`/`read_write` connector fields and mutation endpoint are absent
from the v3 contract; migration removes their persisted JSON remnants.

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
- The fixed desktop provider enum is `minimax`, `deepseek`, `moonshot`, `qwen`,
  `zhipu`, `siliconflow`, `stepfun`, `openai`, `anthropic`, and `composio`. No
  renderer, daemon request, Skill, MCP server, or model output may select an
  arbitrary Keychain item name.
- Tauri exposes only `set(provider, secret)`, `delete(provider)`, and
  `status(provider)` to renderer code. It never exposes a renderer `get` command.
- Python exposes no credential mutation. Its native desktop Credential Broker
  may only call `resolve(provider)` over a per-launch Unix Domain Socket with
  mode `0600`.
- Each Tauri launch generates a random 256-bit broker token. Socket path and
  token are delivered to the daemon in one bounded stdin bootstrap message and
  never written to `.env`, process arguments, SQLite, logs, events, memory,
  checkpoints, artifacts, or diagnostics.
- The inherited stdin pipe remains open as a parent-liveness signal. EOF causes
  the desktop daemon to terminate, preventing an orphan from accepting a later
  launch's traffic or blocking the development port.
- A resolved key exists only in the immediate provider transport callback. It
  is not persisted or retained in a process-wide cache. Credential logs contain
  at most the fixed provider and a boolean presence result.
- Locked, denied, missing, malformed, or unauthenticated credential operations
  fail closed with a user-actionable in-app result; users are never instructed
  to operate Keychain Access manually.
- Logs, events, checkpoints, memory, and artifact manifests store references or
  redacted summaries only.
- The v3 connection broker is Composio Direct/BYO-key. Its scoped project key
  is a WeatherFlow-held credential and remains in Keychain. Provider OAuth and
  refresh tokens remain at Composio and never enter WeatherFlow.
- SQLite may store only opaque connected-account identifiers, connection state,
  Workspace bindings, source identifiers, and bounded derived snapshots.
- Connect Link URLs and link tokens are transient secrets: return them only to
  the initiating desktop client and never persist or log them.

## 10. Data, memory, and provenance

### 10.1 Operational state

SQLite transaction tables own current mutable state:

- tasks, runs, and steps;
- approvals and action results;
- agent runs and lineage;
- workspaces, scopes, and grants;
- checkpoints and cursors;
- immutable per-Run model routes;
- encrypted, retention-bounded provider continuations;
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
- Provider continuations are deleted at terminal Run state and otherwise expire
  after seven days.
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

### 11.4 Bounded brokered integration boundary

- GitHub fetches bounded notifications and repository activity through
  read-only account authorization.
- Gmail fetches bounded unread-message metadata and snippets only; attachment
  bodies and message mutations are outside the automatic-fetch path.
- Google Calendar fetches a bounded upcoming-event window.
- Every fetch result retains provider source IDs and fetch timestamps and is
  stored locally as replaceable derived context.
- Auto-fetch is silent, read-only, interval-bounded, observable in Cockpit, and
  independently disableable for each connector.
- WeatherFlow's scoped Composio project key is resolved from Keychain only at
  the HTTP transport boundary. Provider credentials and refresh tokens remain
  at Composio.
- Managed OAuth uses Composio v3 Connect Link and authoritative connected-
  account state. Handoff creation is not connection completion.
- Before creating an Auth Config, WeatherFlow reads the project-scoped v3.1
  toolkit record and inspects `composio_managed_auth_schemes`. It may create a
  Composio-managed Auth Config only when that list is non-empty and the local
  connector definition has a non-empty reviewed action allowlist.
  `restrict_to_following_tools` is always present and non-empty. Otherwise the
  connection requires an existing user-provided Auth Config and fails closed
  with a typed result. This setup does not add a model-visible capability.
- Only a curated, version-pinned read surface is eligible for automatic fetch.
  A generic Composio execute tool is never exposed to the model.
- Broker execution binds both the opaque connected-account ID and WeatherFlow's
  stable installation user ID. Action versions are pinned per reviewed action,
  not through one cross-toolkit version constant, because GitHub, Gmail, and
  Google Calendar publish independent toolkit versions. The reviewed
  conversation surface covers common GitHub identity/repository/commit/issue/
  pull-request operations, Gmail search/draft/send, and Calendar list/free-time/
  create/update/delete operations; expanding it still requires a fixed action
  slug, strict input/output schemas, scopes, Trust classification, and tests.
  WeatherFlow may expand only a Composio-managed Auth Config to the connector's
  complete reviewed action allowlist after verifying the connected account's
  installation user ID, toolkit, and active state. User-provided Auth Configs
  are never rewritten; insufficient ones fail closed and require
  reauthorization. The complete allowlist makes both modes selectable without
  granting execution authority.
- Every reviewed Composio action also owns an explicit output projection. Only
  named useful fields cross into the normalized Observation; unknown nested
  fields are dropped, credential-shaped values in approved text fields are
  redacted, and HTTP(S) URLs lose user info, query parameters, and fragments.
  Output filtering never relies on a blacklist of provider field names.
- Connector tools use canonical WeatherFlow ToolSpec IDs. A new Run freezes the
  mode-selected specs and an opaque connector route containing the account
  identity. Execution rechecks the current binding, active account state, exact
  frozen identity, scope, ToolSpec version, and Trust decision. Reconnection or
  revocation makes the old Run fail closed. Mutable UI mode cannot affect an
  already-frozen Run, and no connector conversation-grant fields exist.
- A leaf Worker may inherit a Composio route only for reviewed read-only tools
  actually present in its frozen child capability snapshot. The child route is
  copied from the parent Run after rechecking Workspace ownership, account
  identity and scopes. No matching child tool means no route; connector writes
  remain excluded from Worker snapshots.
- Conversation reads execute as `network_read`. Drafting/sending, issue/task
  mutation, calendar writes, and destructive actions persist a normal Action and
  enter Approval before the broker receives any execution request.
- Connected identity, OAuth scope, Workspace scope, Tool visibility, execution
  authority, and Approval remain separate checks. Connector activation is the
  only time WeatherFlow may validate or expand a managed provider allowlist;
  this provider setup is not a per-conversation grant.
- The v3 directory contains GitHub, Gmail, Google Calendar, Slack, Notion,
  Google Drive, Google Sheets, Outlook, OneDrive, Microsoft Teams, Linear,
  Jira, Confluence, Dropbox, GitLab, Discord, Trello, Asana, Airtable, and
  ClickUp. Only the first three support production automatic fetch and
  conversation ToolSpecs in this phase. Every other entry is catalog/identity
  only until its own fixed ToolSpecs, scopes, Trust tests, and executor are
  reviewed; the UI and API must expose that distinction.

Broader email and messaging integrations, Composio Triggers, and a WeatherFlow
cloud proxy remain deferred. Any future connector must be added as a Pack/MCP
capability rather than a new core agent loop.

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

Private chain-of-thought is never stored in or shown through the timeline,
events, diagnostics, logs, memory, checkpoints, or artifacts. Provider-required
continuations are an encrypted protocol-recovery exception with a separate
owner and retention policy; the timeline uses only concise execution summaries
and structured events.

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
- macOS sandbox escape denial for filesystem, network, Keychain, host signals,
  environment inheritance, timeout, and descendant cleanup;
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
- task-dot state transitions;
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
- continuation AEAD tamper detection, model binding, expiry, terminal deletion,
  and absence from logs/events/checkpoints/memory/diagnostics;
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
- Duplicate `client_request_id` or `action_id` never causes duplicate execution;
  a `client_request_id` reused across Workspace or session boundaries fails
  closed instead of returning the original Run.
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
- typed macOS OS sandbox capable of running project scripts, builds, and tests
  with no unsandboxed fallback;
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
- one-click Cockpit connection and silent auto-fetch for the bounded GitHub,
  Gmail, and Google Calendar connector set.
- verified local Skill catalog installation, curated pinned MCP administration,
  and persisted schedule-to-Run Automations with history.

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
17. Model providers cannot widen frozen capabilities or write durable state;
    provider-required continuation data is persisted only by the SharedTurnLoop
    through the encrypted, retention-bounded continuation store. Credentials
    resolve only at their transport boundary.
18. Automations submit ordinary Runs and cannot execute capabilities directly.
19. Skill and MCP catalog installation is explicit, immutable per installed
    snapshot or pinned preset, and never grants authority. Every install uses a
    durable Action/Approval pair; renderer confirmation flags and fabricated
    authorization ids are not accepted, and interrupted execution never retries
    automatically.

## 18. Design completion criteria

This design is complete when an implementation plan can decompose P0-P4 without
making new product-level choices about identity, autonomy, privacy, desktop
behavior, state semantics, storage ownership, or v3.0 scope.

Concrete Python libraries, provider SDK adapters, Tauri UI framework choices,
animation assets, and detailed module filenames are implementation-plan
decisions. They must preserve the contracts and invariants in this document and
must not introduce an alternative execution or authority path.
