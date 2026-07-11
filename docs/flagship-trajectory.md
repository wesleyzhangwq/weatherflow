# WeatherFlow v3 flagship trajectory

P3 is accepted by a deterministic, provider-free fixture for the overloaded
release story. Run it from the repository root:

```bash
make eval
```

`make check` includes the same gate alongside Python, desktop, and Rust checks.
The fixture uses recorded model turns and local fake Research/GitHub providers;
it never contacts or mutates an external service.

## Exercised trajectory

1. A deliberate check-in produces storm weather and the
   `minimal / compact / favor / reduce / silent` RhythmPolicy.
2. The explicit release goal creates a durable parent Run with an immutable
   policy binding and frozen `developer + research` capability surface.
3. `release-preparer`, `researcher`, and `release-validator` execute as durable
   leaf child Runs through `SharedTurnLoop`.
4. Scoped local files, an allowlisted validation command, a source-backed
   research note, a release checklist, and a validation report execute without
   additional user interaction.
5. The GitHub release call becomes a durable Action. The parent parks in
   `WAITING_APPROVAL`; the fake provider has still received zero mutations.
6. Approval resumes the same checkpoint, executes the provider once, commits
   the final result, and appends terminal task behavior as Rhythm evidence.
7. Replaying the original `client_request_id` reuses the completed Run: model
   and provider call counts do not change.

## Deterministic checks

`FlagshipTrajectoryEvaluator` verifies:

- terminal success without failure or ambiguous-side-effect events;
- overload strategy binding without changing the goal;
- the expected frozen capability surface;
- exactly three known leaf Workers and no grandchildren;
- approval precedes the single external execution;
- zero provider calls before approval and exactly one after approval/replay;
- SHA-256 Artifact integrity, validation metadata, source provenance, and
  parent-Cockpit visibility for child artifacts;
- one append-only terminal task-behavior signal after result commit.

The integrated desktop story additionally verifies storm presentation, pure
input and immediate Capsule close, separate active/approval ring states, no
automatic Cockpit opening, structured Action preview, explicit approval,
timeline visibility, and Artifact visibility. Rust tests pin startup to the
Companion, the global shortcut to the Capsule, and the Cockpit to explicit,
non-ambient window policy.
