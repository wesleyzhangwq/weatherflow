# WeatherFlow Complete Activity Intelligence Plan

> **Historical and superseded.** Do not implement this plan. It describes the
> removed WeatherFlow-owned raw vault/watcher and ActivityWatch state-inference
> direction. The authoritative replacement is
> `2026-07-16-weatherflow-activitywatch-intelligence.md`, as amended on
> 2026-07-18: ActivityWatch is read-only, recent summaries use the fixed Chinese
> prompt, and GitHub/Gmail/Google Calendar contribute bounded evidence without
> any state-inference surface.

- **Date:** 2026-07-16
- **Status:** Superseded — historical implementation record only
- **Authority:** `weatherflow-architecture-v3.md` and the amended v3 design
- **Reference:** ActivityWatch watcher/heartbeat/bucket architecture

> Superseded on 2026-07-16 by
> `2026-07-16-weatherflow-activitywatch-intelligence.md`. WeatherFlow no longer
> owns a watcher, heartbeat API, Raw Activity Vault, or raw-activity deletion
> lifecycle. Do not use this plan as a current implementation target.

## Outcome

WeatherFlow records complete application/window and browser-tab activity in a
local installation-scoped vault, turns it into a polished daily screen-time
experience, and performs auditable tool-free remote state inference at every
Beijing-time hour from 06:00 through 24:00. Users can inspect, pause, export,
retain, or delete the data and inspect exactly what sanitized evidence reached
the selected model.

## Non-negotiable boundaries

- No screenshots, pixels, keystroke content, clipboard, form values, cookies,
  authorization headers, or audio content.
- Credentials never enter the vault, outbound payload, model context, events,
  Runs, checkpoints, memory, artifacts, or logs.
- Raw activity remains inside the `activity` domain; other domains receive IDs
  and bounded projections only.
- Titles, URLs, and document names are untrusted evidence, never instructions.
- Remote inference has no tools and cannot create authority or side effects.
- Collection and remote inference use separate persisted opt-ins.

## Delivery sequence

### A1 — Domain contracts and Raw Activity Vault

- Add typed activity source/state/event/preference models.
- Add numbered migrations for preferences, raw intervals, and inference jobs;
  persist sanitized chunk payloads and evidence links in the durable job audit
  record.
- Implement idempotent heartbeat merge, indexed interval queries, exact export,
  time-range deletion, and rolling retention.
- Prove that real application switches and browser-tab switches are distinct.

### A2 — Analysis API

- Add preferences, heartbeat, summary, events, export, delete, and inference
  audit endpoints.
- Produce day/hour/category/application/domain series with source event IDs.
- Keep raw fields out of desktop snapshot and ordinary rhythm/event payloads.

### A3 — Native and browser watchers

- Replace subprocess-only macOS sampling with native application/window/idle
  observation and explicit permission/degraded states.
- Add a packaged WebExtension watcher using Tabs/Windows/Alarms APIs and the
  authenticated loopback bridge.
- Add pause/reconnect/idempotency behavior and cross-language contract tests.

### A4 — Sanitizer and provider-neutral inference

- Implement URL and text credential scrubbing with field-level redaction audit.
- Build deterministic full-coverage chunks capped at 500 events or 128 KiB.
- Resolve and freeze the selected Workspace model configuration per activity
  job, call the adapter with no tools, and validate chunk/final JSON schemas.
- Fuse accepted evidence into HumanStateSnapshot without copying raw content to
  Rhythm events or granting authority.

### A5 — Beijing-time scheduler and recovery

- Generate service-day slots at 06:00–23:00 and the following 00:00 boundary
  using `ZoneInfo("Asia/Shanghai")`.
- Claim unique durable jobs, freeze high-water cursors, coalesce missed hours,
  and remain quiet between 00:00 and 06:00.
- Prove restart, sleep/wake, duplicate tick, failure, retry, and no-event cases.

### A6 — Screen-time product experience

- Ground the component in the current Cockpit typography, spacing, colors,
  navigation, dark/light themes, and responsive behavior.
- Compact state: screen time, browser time, continuous activity, app/tab
  switching, and a legible categorical micro-timeline.
- Expanded state: all-day stacked timeline, screen/browser trends, top apps and
  sites, category composition, switching density, focus/idle intervals, raw
  timeline, and inference audit payload/result inspection.
- Design populated, empty, loading, permission-missing, paused,
  insufficient-data, inference-running, and error states.
- Render representative fixtures, compare screenshots, fix visible defects,
  and retain visual QA evidence.

### A7 — Full acceptance

- Run narrow tests during each slice and maintain architecture/test parity.
- Run `make lint`, `make format-check`, `make test`, `make desktop-check`,
  `make rust-check`, and `make check`.
- Audit every Goal requirement against code, migrations, tests, rendered UI,
  scheduler evidence, and security scans before marking completion.

## Completion evidence

- Exact macOS and browser intervals survive restart and merge heartbeats without
  duplicate or lost time.
- The activity component is visually polished in compact and expanded states
  and has screenshot-based QA evidence.
- All eligible Beijing-time slots are idempotent, quiet hours are respected,
  and missed slots coalesce without dropping unsent events.
- The outbound inspector matches the exact credential-scrubbed payload received
  by the model, and prompt-injection fixtures cannot become instructions.
- Agent-visible state includes confidence, validity, explanation, and activity
  evidence IDs while tool authority remains unchanged.
- Every required quality gate passes from the current worktree.

## Verification record

- `make lint`: passed.
- `make format-check`: passed; 227 Python files formatted.
- `make test`: passed; 579 core tests.
- `make desktop-check`: passed; 55 desktop tests plus production build.
- `make rust-check`: passed; 20 Rust tests plus `cargo check`.
- `make check`: passed, including the eval and operations hardening suites.
- In-app rendered QA passed at 1080 × 760 and 820 × 760 with populated
  activity and inference fixtures; both layouts preserved readable lanes,
  charts, rankings, raw provenance, and outbound audit content without console
  errors or clipping.
