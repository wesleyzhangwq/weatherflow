# WeatherFlow v3 local memory

WeatherFlow memory is local, source-linked context. It is never a capability,
permission, or alternate source of truth.

## Roles

| Role | Durable owner | Contract |
|---|---|---|
| Working context | Run checkpoint | bounded recall assembled for a Run; no separate duplicate store |
| Episodic memory | `episodic_memories` | immutable useful experience with one or more real source event IDs |
| Profile assertions | `profile_assertions` | structured user-editable claims with confidence, status, evidence, origin, timestamps, and optimistic versioning |
| Search index | `memory_search_index` | derived terms only; safe to delete and rebuild from the two owners above |

Memory creation rejects missing events, events owned by another Workspace, and
events marked `secret_ref`. Profile edits append content-free audit events;
the current claim remains owned by the versioned profile row so a future reset
does not leave deleted claim text in the audit ledger.

## Recall boundary

At Run creation WeatherFlow recalls at most five relevant entries and at most
4,000 characters. The frozen checkpoint records their entry and source-event
references. The orchestrator prompt labels the result as context only and
never authority. Recall does not change Workspace scopes, Pack selection,
Agent filters, Trust decisions, or the frozen `RunCapabilitySnapshot`.

`MemoryStore.rebuild_index(workspace_id)` deletes the Workspace's derived index
and deterministically reconstructs it from episodic memories plus active
profile assertions. Retracted assertions are not indexed or recalled.
