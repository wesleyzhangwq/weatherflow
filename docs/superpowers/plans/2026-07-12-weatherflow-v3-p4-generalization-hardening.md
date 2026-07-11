# WeatherFlow v3 P4 Generalization and Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Generalize the verified flagship harness into a locally owned, installable v3.0 product and produce the strongest macOS release artifact possible without user-held signing credentials.

### P4a: Installable extension contracts

- [x] Define versioned Capability Pack, Skill, and Agent Definition manifests with canonical digests, strict path/name/schema validation, and fail-closed unknown fields.
- [x] Add an atomic local package store and explicit installer that updates Workspace pack/agent/skill configuration with optimistic concurrency; model-driven install remains an `install` Action requiring approval.
- [x] Add a Credential Broker that exposes references only and resolves secret values solely at provider transport boundaries.
- [x] Package the three first-party Packs and release-story Agent Definitions using the same public manifest contracts.

### P4b: MCP client and server surfaces

- [x] Implement typed MCP discovery/call transport, normalize discovered tools to canonical ToolSpecs, honor read/write/destructive annotations without granting scopes, and degrade on disconnect/schema drift.
- [x] Register connected MCP tools only for new Run snapshots and execute them through `SharedTurnLoop` plus Trust Plane.
- [x] Expose WeatherFlow Run submission, status, timeline, and approval operations through a minimal stdio MCP server that calls the sole RuntimeContainer path.
- [x] Test discovery, disconnect, schema drift, credential redaction, approval classification, and Run idempotency.

### P4c: Personal Operations and memory completion

- [x] Complete deterministic local task planning, meeting preparation, and rhythm-aware schedule proposal artifacts; Calendar writes remain approved external Actions.
- [x] Add source-linked episodic memory and editable profile assertions, with a rebuildable derived search index and no independent truth store.
- [x] Feed bounded relevant memory into model context without exposing secrets or allowing memory to widen authority.

### P4d: Diagnostics, privacy, reliability, and onboarding

- [x] Add local structured Run metrics and an explicitly requested redacted diagnostic export; never upload telemetry by default.
- [x] Implement retention expiry and independent reset operations for behavior evidence, memory/profile, artifacts, and Workspace data, with deletion audit summaries that do not retain deleted content.
- [x] Add checkpoint-corruption quarantine, bounded model retry/pause semantics, provider-degradation events, and startup recovery audit.
- [x] Add first-run onboarding/status APIs and Cockpit controls for local ownership, Pack/provider health, sensor fallback, retention, and diagnostic export.
- [x] Add security scans for secret markers and forbidden sensor content across durable stores and exported diagnostics.

### P4e: macOS packaging and release validation

- [ ] Replace the shell sidecar shim with a standalone arm64 Python daemon, verify Tauri supervision against it, and build release `.app` and `.dmg` artifacts.
- [ ] Add entitlements, icons/metadata, release scripts, checksum manifest, SBOM/license inventory, and a clean-machine-oriented release checklist.
- [ ] Run unsigned bundle smoke tests and all release gates. Sign/notarize only when valid Apple credentials are present; otherwise record the exact credential-only blocker without weakening verification.
- [ ] Perform the final P0-P4 architecture, privacy, authority, recovery, and distribution audit; commit `release: harden WeatherFlow v3.0`.

No P4 work may add an alternate Run, policy, approval, or state-inference path.
