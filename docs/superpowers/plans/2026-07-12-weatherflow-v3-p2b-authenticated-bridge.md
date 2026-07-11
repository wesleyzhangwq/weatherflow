# WeatherFlow v3 P2b Authenticated Desktop Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Provide a token-authenticated loopback bridge with ordered cursor-based event recovery for the Tauri shell.

**Architecture:** A per-launch token supplied through Settings gates HTTP and WebSocket handshakes without entering events/logs. EventLedger exposes a global ordered cursor read. WebSocket sends backlog after cursor then polls for new committed events; desktop can fall back to current snapshots when a cursor is invalid.

### Task 1: Global event cursor

- [ ] Add failing tests for ordered `list_after(cursor)`, initial backlog, unknown cursor, and limit bounds.
- [ ] Implement connection-bound/global reads ordered by `(recorded_at,id)` and explicit `UnknownEventCursor`; commit `feat: add ordered Event Ledger cursors`.

### Task 2: HTTP/WebSocket authentication and event stream

- [ ] Add Settings bridge token, auth middleware, and tests proving configured HTTP requests reject missing/wrong tokens while unconfigured dev mode remains usable.
- [ ] Add `WS /v1/events?cursor=` with token header/query support, typed Event JSON, backlog/reconnect tests, and invalid-cursor close code instructing snapshot refresh.
- [ ] Ensure token is absent from schemas/events/errors; commit `feat: add authenticated desktop event bridge`.

### Task 3: P2b audit

- [ ] Document loopback token/cursor contracts; run full gates and commit `docs: describe WeatherFlow desktop bridge`.

P2b ends here. P2c builds Companion/Capsule/Cockpit web surfaces and Tauri source; P2d adds native metadata/supervision adapters.
