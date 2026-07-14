# WeatherFlow v3 Tools and Automation Plan

## Goal

Deliver one coherent Cockpit Tools surface for verified Skills, curated MCP
Servers, schedule-to-Run Automations, LLM configuration, and Composio, while
preserving the v3 Run Coordinator and Trust Plane as the sole execution path.

## Product contracts

- Conversation remains the primary Cockpit destination.
- Automations are schedules that submit ordinary durable Runs. They are not a
  workflow engine and never execute tools directly.
- Skill installation copies a verified immutable snapshot into a Workspace.
  The source checkout is not read at Run time.
- MCP presets are curated and version-pinned. The renderer cannot provide an
  executable, arbitrary environment, or package URL.
- Skill and MCP metadata never grants authority. Every capability is filtered
  by Workspace scope and checked again by Trust at execution.
- Install, external-write, and destructive effects retain their normal approval
  requirements.
- Connection or catalog changes affect future Runs only.

## Workstream 1: Skill catalog

1. Scan and validate selectable `SKILL.md` packages from the configured local
   `wesley-skills` root.
2. Expose a typed catalog with Chinese metadata, source provenance, validation
   state, and per-Workspace installation state.
3. Adapt a selected entry into the existing verified extension package format
   and install it through `PackageInstaller`.
4. Support explicit removal from a Workspace without altering the source repo.
5. Test traversal, symlink, invalid metadata, duplicate ID, install, removal,
   and immutable-snapshot behavior.

## Workstream 2: Curated MCP catalog

1. Define a small fixed catalog of common servers appropriate for a local
   personal agent harness, with pinned package versions and safe arguments.
2. Persist install and enabled state per Workspace without storing secrets in
   renderer-visible data.
3. Install packages into the WeatherFlow internal root only after explicit user
   action; start and discover tools only when enabled.
4. Close transports on disable and daemon shutdown. Registry changes apply only
   to capability resolution for future Runs.
5. Test preset allowlisting, installation boundaries, lifecycle, health,
   annotation normalization, and execution-time approval enforcement.

## Workstream 3: Automations

1. Add durable Automation and AutomationRunLink storage with optimistic
   updates, timezone-aware schedule specs, and enabled/paused state.
2. Implement create, edit, pause, resume, delete, run-now, list, detail, and
   history operations.
3. Add one scheduler lifecycle owned by the Python daemon. Each firing submits
   one idempotent Run through the existing runtime container.
4. Coalesce overdue occurrences to at most one Run per Automation on startup and
   advance the next occurrence deterministically.
5. Test recurrence, daylight-saving/timezone behavior, idempotency, restart,
   history, and the no-direct-tool-execution invariant.

## Workstream 4: Cockpit

1. Keep core navigation for conversation, Runs, and status weather.
2. Add a Tools section containing Automations, Skills, MCP Servers, LLM Models,
   and Composio; retain Settings for system/privacy/diagnostics.
3. Build Automation as filter/search/list plus detail editor and Run history,
   following the supplied Codex reference without copying its branding.
4. Build searchable Skill and MCP catalogs with clear installed/enabled/health
   states and explicit security consequences.
5. Move existing model and connection controls into their dedicated routes and
   keep Chinese labels, responsive sizing, keyboard use, and IME composition.

## Acceptance

- A user can select a Workspace, install one `wesley-skills` Skill, start a new
  conversation Run, and observe that frozen Skill guidance is available.
- A user can explicitly install and enable a curated MCP preset, inspect its
  health/tools, and use it only through normal Run/Trust/Approval handling.
- A user can create, pause, resume, edit, run, and delete an Automation; every
  execution appears as a normal Run with linked history and no catch-up burst.
- LLM and Composio behavior remains functional after navigation is reorganized.
- The supplied visual reference is matched in hierarchy, density, and list/detail
  behavior, while WeatherFlow's conversation-first identity remains intact.
- `make lint`, `make format-check`, `make test`, `make desktop-check`,
  `make rust-check`, and `make check` all pass.
