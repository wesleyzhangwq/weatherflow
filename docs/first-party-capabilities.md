# WeatherFlow v3 first-party capabilities

P3a provides three built-in Capability Packs behind the public `ToolSpec`,
provider, Workspace, Trust Plane, Run snapshot, and Artifact Store contracts.
Installing a Pack describes what may exist; it does not grant authority.

| Pack | Tools | Effect boundary |
|---|---|---|
| `developer` | scoped file read/write, Git status, allowlisted argv execution, GitHub release read/write | local writes and commands are sandbox decisions; GitHub writes require approval |
| `research` | bounded source retrieval and a provenance-aware Markdown artifact | network read only; provider absence hides the tool |
| `personal_operations` | Calendar read and event creation | reads are bounded; event creation requires approval |

## Resolution

For the built-in catalog, `RuntimeContainer` resolves only tool IDs belonging
to `Workspace.installed_packs`. The supervised policy then removes unavailable
tools and tools whose required scopes were not granted. The remaining canonical
specifications are frozen into the Run capability snapshot and cannot change
during that Run. Unknown Pack names fail before a Run is created.

The default local Workspace installs only `developer` and grants
`workspace:read`, `workspace:write`, and `workspace:execute`. Research,
Calendar, and GitHub provider tools are unavailable unless a typed provider is
explicitly supplied. Provider credentials stay inside provider implementations
and are never returned through tool observations, events, checkpoints, or
artifacts.

## Execution boundaries

- File paths resolve beneath an action root after symlink resolution and may
  never enter the WeatherFlow internal root.
- File writes are atomic and return before/after digests, a bounded diff, and
  recovery metadata.
- Commands are argv-only, never use a shell, have a fixed executable allowlist,
  receive a reduced environment, and have time and output bounds.
- Research results retain title, URL, retrieval time, bounded excerpt, and a
  numbered citation. The report is an immutable content-addressed artifact.
- `calendar.create_event` and `github.create_release` reject direct execution
  without an approved Action context and idempotency key.
- A recovered ambiguous external mutation enters `NEEDS_REVIEW`; it is never
  blindly retried.

These are capability adapters, not a second execution path. Orchestrators and
future Workers invoke them only through `SharedTurnLoop` and the Trust Plane.
