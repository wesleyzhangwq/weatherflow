# WeatherFlow v3 P2c Desktop Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the Companion, pure-input Capsule, and explicit Cockpit as one tested React frontend plus a thin Tauri multi-window shell.

**Architecture:** URL/window labels select one React surface. A typed bridge client consumes backend snapshots/events and submits commands. Tauri owns window lifecycle only; weather logic and authority remain in Python. Browser fallback enables frontend tests/build without native runtime.

### Task 1: Frontend foundation and typed bridge

- [ ] Scaffold `desktop/` with Vite/React/TypeScript/Vitest, strict lint/type/build gates, typed API/event client, reconnect snapshot fallback, and tests.
- [ ] Commit `feat: scaffold WeatherFlow desktop frontend`.

### Task 2: Companion and Capsule

- [ ] Implement transparent companion character, backend weather tokens, separate Run ring/badge, reduced motion, no proactive text/bubble, click/global activation hook.
- [ ] Implement one-field capsule with paste/drop, submit acknowledgement then immediate close, no Cockpit auto-open. Test all invariants; commit `feat: build Companion and command Capsule`.

### Task 3: Explicit Cockpit

- [ ] Implement explicit-only tasks, approvals, artifacts, timeline/evidence, settings/diagnostics views over typed bridge data. Test approval actions and that no Run event auto-opens Cockpit.
- [ ] Commit `feat: build explicit WeatherFlow Cockpit`.

### Task 4: Thin Tauri source and frontend verification

- [ ] Add Tauri v2 config/Rust commands for companion/capsule/cockpit labels, transparent window setup, global shortcut/tray placeholders, and packaged Python sidecar declaration without business logic.
- [ ] Run npm locked install, lint, typecheck, tests, and production build. Record Cargo-unavailable native compile separately; commit `build: add WeatherFlow Tauri shell` and docs.

P2c ends here. P2d implements daemon supervision and privacy-safe macOS activity metadata, then performs every verification possible without installing a missing Rust toolchain.
