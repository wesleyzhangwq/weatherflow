# WeatherFlow ActivityWatch Intelligence Plan

- **Date:** 2026-07-16
- **Status:** Complete — implementation contract amended on 2026-07-18
- **Authority:** `weatherflow-architecture-v3.md` and
  `docs/superpowers/specs/2026-07-12-weatherflow-v3-design.md`
- **Supersedes:** `2026-07-16-weatherflow-complete-activity-intelligence.md`

## Outcome

ActivityWatch remains the independent and immutable raw activity source.
WeatherFlow reads it strictly through a bounded loopback gateway, stores only
derived tasks, attempts, summary revisions, statistics, Category-rule versions,
dependencies, and ActivityWatch plus per-source connector evidence references.
Recent summaries use a fixed, versioned Simplified-Chinese prompt and bounded
read-only GitHub, Gmail, and Google Calendar snapshots together; the Watch panel
exposes facts and summaries only, never state inference.

## 2026-07-18 contract amendment

This amendment overrides every earlier task in this plan that could be read as
allowing editable summary guidance, persisted prompt text, GitHub-only summary
context, or ActivityWatch state inference. The only editable summary setting is
the model selection. The prompt is code-owned, versioned, untrusted-data-safe,
and requires Simplified-Chinese narrative. Each summary window independently
collects bounded read-only coverage from GitHub, Gmail, and Google Calendar and
records per-source evidence refs and missing/stale status. No inference table,
semantic operation, HTTP endpoint, confidence card, or Watch state assessment
may be reintroduced. Generated connector synopses and coverage prose are
Simplified Chinese; a source-language string may remain only as visibly quoted
bounded untrusted evidence.

## Delivery sequence

### W1 — Source cutover

- Remove the Tauri activity sampler, WeatherFlow browser watcher, renderer
  polling hook, heartbeat endpoint, raw-event tables, raw retention, raw export,
  and raw deletion.
- Implement an ActivityWatch client whose public surface contains only `GET`
  operations and the read-only `POST /query/`.
- Validate the fixed loopback API root and provide an isolated short-lived
  `mode=ro`, `query_only` SQLite diagnostic fallback.

### W2 — Fixed windows and durable ledger

- Generate `Asia/Shanghai` six-hour, 24-hour-at-06:00, Monday-week,
  1970-01-05-anchored biweekly, and calendar-month half-open windows.
- Create deterministic task IDs and durable task, attempt, revision,
  dependency, evidence, Category-version, and source-state tables. Summary
  revisions record per-source GitHub/Gmail/Google Calendar coverage and
  evidence refs, not state inference records.
- Make expired running leases safely retryable and prevent duplicate task or
  revision creation.

### W3 — Recovery and finalization

- On every daemon start, probe ActivityWatch, discover buckets/data range/rules,
  recover leases, enumerate every theoretical window, and backfill missing,
  failed, retryable, or non-final tasks chronologically.
- Permit provisional summaries only after 15 minutes and final summaries only
  after 60 minutes plus a fresh source-window query.
- Append a new provisional revision when delayed data changes the source
  watermark; never overwrite history.

### W4 — Statistics, Chinese summaries, and model boundary

- Recalculate application time, dynamic Category time, AFK time, and switches
  from ActivityWatch for every hierarchy level.
- Preserve observed ActivityWatch facts and recomputable statistics without
  generating or persisting programming, communication, meeting, focus, or
  context-state inference.
- Use one code-owned, digest-versioned Simplified-Chinese prompt. Users may
  select the model route but cannot view, submit, store, or edit prompt text.
- Send models only bounded statistics, at most 120 sanitized ActivityWatch
  evidence excerpts, optional lower-level narrative, independently bounded
  read-only GitHub/Gmail/Google Calendar snapshots, explicit untrusted-data
  delimiters, and no tools. Record per-source coverage/evidence refs and return
  Chinese narrative only.

### W5 — Semantic Agent surface

- Add fixed-purpose read tools for current observed facts, recent activity,
  bounded range, application usage, Category usage, AFK, switches, and summary
  history. Do not add state-inference or inference-evidence tools.
- Do not accept arbitrary ActivityWatch query source from a model.
- Keep all tools `observe` and installation-scoped; they grant no execution
  authority.

### W6 — Watch UI

- Add an independent Cockpit Watch destination.
- Source live facts directly from ActivityWatch through the daemon.
- Source summaries, trends, retries, failures, and task ledger data from the
  derived WeatherFlow database.
- Show ActivityWatch source health, current app, AFK, duration, timeline,
  application/Category distribution, Chinese summaries, GitHub/Gmail/Google
  Calendar coverage, trends, and task ledger. Do not show a state assessment,
  inference history, confidence, or inference evidence.
- Render titles and URLs only as visibly untrusted inert text.

### W7 — Completion audit

- Run focused tests while implementing and the full required loop:
  `make lint`, `make format-check`, `make test`, `make desktop-check`,
  `make rust-check`, and `make check`.
- Verify the live local ActivityWatch API without exposing raw titles or URLs.
- Audit every user requirement against source, migrations, tests, API behavior,
  rendered UI, and recovery evidence before marking this plan complete.

## Completion audit

- **Independent sole source:** ActivityWatch remains an external process and the
  only raw activity owner. WeatherFlow's native sampler, browser extension,
  heartbeat ingest API, raw vault, raw export, and raw retention paths were
  removed.
- **Strict read-only access:** Ordinary access is fixed to
  `http://127.0.0.1:5600/api/0` and exposes only GET reads plus ActivityWatch's
  read-only `/query/`. The optional SQLite fallback requires an explicit
  historical-analysis, diagnostic, or API-gap purpose and uses a short-lived
  `mode=ro`, `query_only` connection.
- **Bounded model context:** Semantic queries enforce time, event-count, bucket,
  and byte limits. Raw facts are transient for one tool-free model turn;
  persisted output is an allowlisted structured derivation rather than titles,
  URLs, applications, bucket IDs, event IDs, or AFK records.
- **Derived database ownership:** Migration 27 replaces the old raw activity
  tables with source state, Category versions, task ledger, attempts, revisions,
  dependencies, statistics, and ActivityWatch plus per-source connector evidence
  references. Revisions
  retain summary type, exact window, attempts, completion, statistics,
  Chinese narrative, evidence, Category rules, provider/model/configuration,
  fixed prompt and statistics versions, request digest, redactions, usage, and
  source watermark.
- **Fixed schedules:** The planner covers four six-hour stages, the distinct
  24-hour window ending at 06:00, Monday weeks, a 1970-01-05-anchored biweekly
  cadence, and calendar months in `Asia/Shanghai`.
- **Grace and revision semantics:** Tasks become eligible for provisional work
  after 15 minutes and cannot finalize before 60 minutes plus a fresh raw-window
  read. Changed evidence appends another provisional revision; stable evidence
  finalizes without overwriting earlier revisions.
- **Idempotent recovery:** Startup probes ActivityWatch, discovers its range and
  Category rules, recovers expired leases, enumerates every theoretical window,
  inserts deterministic tasks/dependencies, and processes missing, failed,
  retryable, or non-final tasks chronologically. It does not use a single
  last-summary cursor.
- **Hierarchy and provenance:** Every summary level recalculates exact statistics
  from ActivityWatch. Higher levels may reference lower narrative, but retain
  raw-window statistics, source watermark, evidence refs, and dependency edges.
- **Dynamic Categories:** Normalized ordered rules and their digest are recorded
  per revision. Rule changes mark old revisions as legacy and make affected
  tasks eligible for regeneration without destroying reproducibility.
- **Facts and narrative boundary:** Live facts, AFK state, timeline records,
  and recomputable statistics remain facts. Summary prose is a bounded Chinese
  narrative, never a programming, communication, meeting, focus, or context-
  fragmentation state assertion; no inference record exists.
- **Semantic Agent surface:** Fixed-purpose observe tools cover current facts,
  recent activity, bounded ranges, application usage, Category usage, AFK,
  switches, and summary history. Arbitrary ActivityWatch query source is not
  model-accessible; no inference or inference-evidence operation exists.
- **Watch product surface:** Cockpit has an independent Watch destination with
  live source health/current facts, AFK and duration, today's timeline,
  application and Category distributions, Simplified-Chinese summaries,
  GitHub/Gmail/Google Calendar coverage, weekly/monthly trends,
  pending/retry/failed tasks, regeneration, and evidence inspection. It has no
  state assessment, confidence, or inference surface.
- **Untrusted-data and authority boundary:** Titles, URLs, and labels are inert
  text. Activity tool batches are rejected, raw observations disable tools and
  provider continuations, structured results are schema-validated, and
  activity-tainted assistant context is omitted from follow-up Runs.
- **Deletion and physical erasure:** Activity reset cancels pending tainted Runs,
  deletes provider continuations, clears replay state, scrubs activity tool and
  assistant content, clears Run summaries and result events, deletes the derived
  activity ledger, and runs secure SQLite checkpoint/VACUUM compaction. Preview
  and deleted counts remain equal, and byte-level tests prove removed sentinels
  are absent from the main database and WAL.

## Verification record

- `make lint`: passed.
- `make format-check`: passed; 238 Python files formatted.
- `make test`: passed; 653 core tests.
- `make eval`: passed; 1 evaluation.
- `make security-check`: passed; 6 hardening tests.
- `make desktop-check`: passed; 56 desktop tests plus production build.
- `make rust-check`: passed; 18 Rust tests plus `cargo check`.
- `make check`: passed with every required gate above.
- `make sidecar-check`: passed for ordinary bridge health and Tauri private
  stdin bootstrap.
- Rebuilt arm64 sidecar SHA-256:
  `1c66c8b71e24195e810d58f6134f0a4ccd04d21f1e31b17b319335698a7fd271`.
- Live local ActivityWatch smoke: server `v0.13.1 (rust)`, three buckets,
  Category query and current AFK read succeeded through the loopback API; the
  smoke output deliberately emitted no application name, title, or URL.
- Independent final invariant audit found no remaining P0 or P1 issue.
