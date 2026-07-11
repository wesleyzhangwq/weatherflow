# WeatherFlow v3 P4d Diagnostics, Privacy, Reliability, and Onboarding Plan

**Goal:** Make the local-first harness inspectable, resettable, recoverable, and understandable without creating telemetry, authority, or state-inference side paths.

## P4d1: Local metrics and explicit diagnostic export

- [x] Derive structured Run metrics from durable Run/Action/Event facts; do not add an upload client or background telemetry loop.
- [x] Create an explicitly requested, redacted diagnostic bundle beneath the Workspace internal root with a manifest, checksums, schema version, and bounded content.
- [x] Prove secrets and private signal payloads do not enter diagnostic output.

## P4d2: Retention and independent reset

- [x] Define retention policy and preview models for behavior evidence, episodic memory, profile assertions, artifacts, and Workspace-owned data.
- [x] Execute each reset only through an explicit service/API operation, delete physical artifact blobs when unreferenced, and rebuild derived views/indexes.
- [x] Append deletion audit summaries containing counts and category/time bounds but no deleted content.

## P4d3: Recovery and degradation

- [x] Validate checkpoint shape before resume; quarantine corrupt checkpoint bytes/rows and move the Run to `NEEDS_REVIEW` with a content-free audit event.
- [x] Add bounded retry for retryable model failures and pause after exhaustion without fabricating success.
- [x] Record provider/MCP degradation and startup recovery decisions; recover safe non-terminal Runs and leave ambiguous external Actions for review.

## P4d4: Onboarding and status surfaces

- [x] Add first-run local-ownership preferences and status APIs for Packs, providers, behavior sensor fallback, retention, recovery, and diagnostic export.
- [x] Add Cockpit controls that explain local storage, show degraded components, expose retention/reset previews, and require explicit clicks for export/reset.
- [x] Keep the ambient companion display-only and silent.

## P4d5: Durable-store security scan and gates

- [x] Scan events, checkpoints, memory/profile, manifests, diagnostic bundles, and configuration for secret markers and forbidden raw sensor fields.
- [x] Add a repository gate that fails on detected durable leaks while allowing explicit credential references.
- [x] Run `make check`, a clean database recovery/reset scenario, and a diagnostic-bundle inspection before closing P4d.

Each slice follows observed RED → implementation → focused verification → full
`make check` → atomic commit. P4d must not introduce network telemetry, silent
deletion, alternate approval handling, or raw behavior-content capture.
