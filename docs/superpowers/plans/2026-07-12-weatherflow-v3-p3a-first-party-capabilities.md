# WeatherFlow v3 P3a First-Party Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Provide the bounded Developer, Research, and Calendar tools required by the overloaded-release flagship story.

### Task 1: Secure local Developer executors

- [x] Implement workspace read/write, git status/diff, and allowlisted command execution with root/symlink checks, no shell, time/output bounds, diff/recovery metadata, and tests for traversal/internal-root rejection.
- [x] Register canonical ToolSpecs and executors; commit `feat: add secure Developer capabilities`.

### Task 2: Research provider and artifacts

- [x] Define source-backed ResearchProvider protocol, bounded network-read executor, citation/result normalization, and report artifact writer. Test provenance, unavailable degradation, and output bounding.
- [x] Commit `feat: add source-backed Research capabilities`.

### Task 3: Calendar and release providers

- [x] Define CalendarProvider/GitHubProvider protocols and read/external-write executors. Calendar/release mutations remain APPROVE and use Action idempotency keys. Test no provider mutation before approval and exactly-once after approval.
- [x] Commit `feat: add supervised Calendar and release capabilities`.

### Task 4: Catalog wiring and audit

- [x] Wire first-party specs/executors into RuntimeContainer by installed Workspace packs, retain the smallest frozen surface, run full gates, and document boundaries.
- [x] Commit `docs: describe WeatherFlow first-party capabilities`.

P3a ends here. P3b implements bounded leaf Worker delegation; P3c validates the complete flagship trajectory.
