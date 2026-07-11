# WeatherFlow v3 P2d Native Supervision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the Tauri shell supervise/authenticate the Python daemon and emit only privacy-safe macOS activity aggregates.

### Task 1: Daemon supervisor

- [ ] Implement random loopback port reservation, per-launch token, sidecar spawn/attach, health check, bounded exponential restart, background preference, and in-memory bridge injection. Test pure backoff/state logic in Rust.
- [ ] Ensure token/credentials never persist; commit `feat: supervise WeatherFlow daemon sidecar`.

### Task 2: macOS activity metadata adapter

- [ ] Implement native idle sampling and local frontmost-app-to-coarse-category mapping; raw app identity never crosses command response. Aggregate active/idle/category seconds and switch count in TypeScript before posting `ActivityMetadata`.
- [ ] Add permission/unavailable fallback and schema tests forbidding raw fields; commit `feat: add privacy-safe macOS activity adapter`.

### Task 3: P2 acceptance

- [ ] Verify capsule click/shortcut, close-after-acceptance, weather without bubble, ring transitions, explicit Cockpit, approval, daemon offline/recovery, cursor refresh, reduced motion, and metadata fallback through unit/integration/static contracts.
- [ ] Run Python/full frontend/Cargo gates; document any packaging-only Xcode limitation; commit `docs: complete WeatherFlow v3 P2 desktop and Rhythm`.

P2 ends here. P3 builds the flagship Developer/Research/Calendar vertical slice and bounded Worker delegation.
