# WeatherFlow v3 Worker delegation

P3b adds bounded background delegation while preserving one execution model.
The Orchestrator and every Worker execute through `SharedTurnLoop`; a Worker is
not a second workflow engine or an in-memory helper task.

## Durable hierarchy

Each accepted delegation gets a deterministic `client_request_id` derived from
the parent Run and delegation step. `WorkerCoordinator` creates an ordinary
child Run, copies the permitted subset of the parent's immutable capability
snapshot, and stores the Worker's private transcript in the child's own durable
checkpoint. Replaying a completed delegation reuses that child Run and does not
repeat model work or tool effects.

The parent Event Timeline receives idempotent `worker.started` and
`worker.completed` lifecycle events. The parent model sees only a bounded
`CompactWorkerResult`: agent ID, success/failure, a short summary, and Artifact
IDs. It never receives the Worker's full transcript or private reasoning.

## Authority and recursion

- Every registered Worker definition has `is_leaf=true`; a nested delegation
  deterministically fails the child Run and cannot create a grandchild.
- A Worker can only remove tools from the parent's frozen snapshot. Its Agent
  Definition and tool filter cannot add scopes, tools, or authority.
- `external_write`, `install`, `destructive`, and `sensitive` tools are removed
  from Worker snapshots. The Orchestrator owns approval-bearing actions.
- Missing Worker definitions and failed Workers become bounded parent
  observations, not uncaught process failures or fabricated success.

## Concurrency and built-ins

The process-wide default maximum is three active Workers. Calls with the same
delegation identity are serialized as an additional idempotency guard.

`RuntimeContainer` installs three release-story definitions:

- `release-preparer`: scoped reads, writes, and Git status;
- `release-validator`: scoped reads, Git status, and allowlisted commands;
- `researcher`: source-backed research only.

These definitions are built-in bootstrap defaults. P4 adds installable Agent
Definition packaging without changing this authority model.
