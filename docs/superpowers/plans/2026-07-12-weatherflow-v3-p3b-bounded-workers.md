# WeatherFlow v3 P3b Bounded Worker Delegation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add durable, restart-safe leaf Worker delegation without creating a second agent loop or widening parent authority.

### Task 1: Durable Worker coordinator

- [x] Add a Worker definition registry and coordinator that creates idempotent child Runs, copies only the authorized subset of the parent capability snapshot, and executes the child through `SharedTurnLoop`.
- [x] Record parent-readable Worker lifecycle events while keeping the private Worker transcript in its own checkpoint.

### Task 2: Leaf and compact-result contracts

- [x] Force Worker definitions to be leaf agents, convert nested delegation into a deterministic failed Worker Run, and return only `CompactWorkerResult` plus Artifact IDs to the parent.
- [x] Handle missing definitions and non-success outcomes as bounded observations rather than uncaught runtime failures.

### Task 3: Bounded concurrency and recovery

- [x] Enforce a default global maximum of three active Workers with tests that schedule four concurrent delegations.
- [x] Prove retry/restart idempotency: a completed child Run is reused and its side effects/model work are not repeated.

### Task 4: Shared-loop integration and audit

- [x] Replace the placeholder delegation observation in `SharedTurnLoop`, wire built-in release-story Worker definitions in `RuntimeContainer`, and test parent/child request surfaces.
- [x] Run all gates, document the Worker boundary, and commit `feat: add bounded leaf Worker delegation`.

P3b ends here. P3c assembles and evaluates the complete overloaded-release trajectory.
