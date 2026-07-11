# WeatherFlow v3 P2a Rhythm Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert deliberate signals and privacy-safe activity metadata into evidence-aware HumanStateSnapshot, behavior-oriented RhythmPolicy, and stable WeatherPresentation.

**Architecture:** Raw signals are append-only Events. A deterministic feature extractor and estimator derive six independent dimensions; a cache repository stores only the latest rebuildable snapshot. Weather and policy are pure projections. No desktop code contains state-to-weather logic.

**Tech Stack:** Python 3.12, Pydantic v2, SQLite, pytest-asyncio.

---

## Locked contracts

- Accepted ambient metadata: active/idle duration, app-switch count, and coarse category totals only.
- Screenshots, window titles/content, keystrokes, clipboard, raw audio, and app-specific document names have no schema fields.
- Six dimensions each carry value, confidence, trend, evidence, contradiction, and freshness.
- Low-confidence, conflicting, or expired state projects to `mixed`.
- RhythmPolicy changes interaction/execution strategy, never the user goal; proactivity is always silent.

### Task 1: Signal and snapshot contracts

**Files:** Create `rhythm/{__init__.py,models.py}` and contract tests.

- [ ] Define deliberate check-in/correction and `ActivityMetadata` discriminated signals with `extra=forbid`; test forbidden raw-content keys are rejected.
- [ ] Define six `DimensionName` values, `DimensionEstimate`, `HumanStateSnapshot`, `RhythmPolicy`, and `WeatherPresentation` with frozen bounds/UTC validity.
- [ ] Test full JSON round-trip and fixed weather vocabulary; commit `feat: define privacy-safe Rhythm contracts`.

### Task 2: Deterministic feature extraction and projections

**Files:** Create `rhythm/estimator.py`, `rhythm/projections.py`, focused tests.

- [ ] Test overload, fragmented, blocked, flow, recovery, steady, conflicting, low-coverage, and expired fixtures. Explicit corrections receive highest evidence weight.
- [ ] Implement rolling-window aggregation into all six dimensions, confidence/freshness/trend, summary, evidence IDs, and estimator version. Implement pure policy/weather projection; weather scenes are clear/fair/fog/storm/still/night/mixed.
- [ ] Verify and commit `feat: derive Rhythm state and weather`.

### Task 3: Durable signal ingestion and current snapshot API

**Files:** Add migration 8; create snapshot repository/service; extend bootstrap/API/tests.

- [ ] Cache latest snapshot JSON per Workspace with version; ingest signal as Event with retention/sensitivity, recompute, cache, and append `rhythm.snapshot_derived` atomically.
- [ ] Add `POST /v1/rhythm/signals`, `GET /v1/rhythm/current`, and include weather/policy in `GET /v1/desktop/snapshot` alongside latest Run state. Test corrections create new facts rather than mutate old events.
- [ ] Run full checks; commit `feat: expose durable Rhythm Intelligence`.

### Task 4: P2a documentation and audit

- [ ] Document signal privacy boundary and backend-only weather projection.
- [ ] Run locked sync/full checks; commit `docs: describe WeatherFlow Rhythm Intelligence`.

P2a ends here. P2b adds token-authenticated loopback event/snapshot bridging; P2c/P2d build desktop surfaces and the macOS metadata adapter.
