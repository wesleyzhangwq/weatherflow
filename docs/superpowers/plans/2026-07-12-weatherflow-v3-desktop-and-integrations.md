# WeatherFlow v3 Desktop Experience and Integrations Plan

**Goal:** Make the macOS shell comfortable for daily use and add a truthful,
bounded connection surface for GitHub, Gmail, and Google Calendar.

## Task 1: Compact movable Companion

- [x] Add failing desktop/Rust contracts for a 128×128 startup window, a native
  drag region, Chinese accessibility labels, and separate explicit Capsule and
  Cockpit controls.
- [x] Replace the oversized character with a compact micro-weather orb and
  verify click, drag, Run ring, weather, and reduced-motion behavior.

## Task 2: Cancellable Capsule

- [x] Add failing tests for an explicit close button and Escape cancellation.
- [x] Implement Chinese pure-input copy, retain-on-error, immediate
  close-after-acceptance, and a compact anchored window.

## Task 3: Chinese conversation-first Cockpit

- [x] Add failing tests for the Chinese primary journey and readable responsive
  layout contracts.
- [x] Rebuild the Cockpit around a persistent left navigation and a dominant
  conversation workspace modeled after the local OpenHuman/harness reference.
  Runs, rhythm, connections, approvals/artifacts, and settings become dedicated
  secondary views; keep Cockpit explicit-only.

## Task 4: Mainland-China model providers

- [x] Generalize the provider adapter without creating a second turn loop.
- [x] Add visible presets for MiniMax, DeepSeek, Moonshot/Kimi, Alibaba Model
  Studio/Qwen, Zhipu GLM, SiliconFlow, and StepFun.
- [x] Expose model name and HTTPS API endpoint in settings; store API keys only
  in Keychain and verify before activation.

## Task 5: Connector state and auto-fetch core

- [ ] Add failing migration/repository/service/API tests for exactly three
  connectors, explicit connect/disconnect, read-only auto-fetch, bounded
  intervals, status, source IDs, timestamps, and redacted credentials.
- [ ] Implement provider-neutral connector protocols, local derived snapshots,
  background scheduling, manual sync, and event-ledger audit summaries.

## Task 6: First-party adapters and Cockpit connection UX

- [ ] Implement GitHub device/CLI authorization and bounded notification fetch.
- [ ] Implement Google desktop OAuth loopback for Gmail metadata and Calendar
  events once the OAuth client configuration is present.
- [ ] Add one-click browser handoff, status polling, toggles, manual refresh, and
  actionable setup errors to Cockpit.

## Task 7: Verification

- [ ] Run narrow tests while developing, then every required Make target and
  `make check`.
- [ ] Cold-launch with `pnpm dev:app`, verify drag/cancel/Chinese scaling, and
  perform real read-only fetches for every locally configured provider.
