# WeatherFlow v3 first-party capabilities

P3a provides three built-in Capability Packs behind the public `ToolSpec`,
provider, Workspace, Trust Plane, Run snapshot, and Artifact Store contracts.
Installing a Pack describes what may exist; it does not grant authority.

| Pack | Tools | Effect boundary |
|---|---|---|
| `developer` | scoped file read/write, Git status, and allowlisted argv execution | local writes and commands are sandbox decisions; connected GitHub operations use the canonical Composio tools |
| `research` | bounded source retrieval and a provenance-aware Markdown artifact | registered only when a reviewed typed provider is injected |
| `personal_operations` | rhythm-aware day plans, meeting prep, schedule proposals, Calendar read/write | planning outputs are local artifacts; Calendar access uses a frozen connected-account route and event creation requires approval |

## Resolution

For the built-in catalog, `RuntimeContainer` resolves only tool IDs belonging
to `Workspace.installed_packs`. The supervised policy then removes unavailable
tools and tools whose required scopes were not granted. The remaining canonical
specifications are frozen into the Run capability snapshot and cannot change
during that Run. Unknown Pack names fail before a Run is created.

The default local Workspace installs `developer` and `personal_operations` and grants
`workspace:read`, `workspace:write`, and `workspace:execute`. Research,
and legacy direct GitHub provider tools are absent from the production catalog
unless a reviewed typed provider is explicitly supplied. Calendar-backed tools
become visible only when an active Google Calendar binding is frozen for the
Run; their production adapter delegates to the same reviewed Composio gateway
as the canonical connector tools. Provider credentials stay inside that gateway
and are never returned through tool observations, events, checkpoints, or artifacts.

## Execution boundaries

- File paths resolve beneath an action root after symlink resolution and may
  never enter the WeatherFlow internal root.
- File writes are atomic and return before/after digests, a bounded diff, and
  recovery metadata.
- Commands are argv-only, never use a shell, have a fixed executable allowlist,
  receive a reduced environment, and have time and output bounds.
- Research results retain title, URL, retrieval time, bounded excerpt, and a
  numbered citation. The report is an immutable content-addressed artifact.
- Day plans reduce commitment density and add recovery space when the frozen
  RhythmPolicy reports overload. Meeting prep and schedule proposals preserve
  Calendar and rhythm provenance in immutable local artifacts.
- A schedule proposal never mutates Calendar. Accepting a proposed block is a
  separate `calendar.create_event` external Action and therefore requires
  explicit approval.
- `calendar.create_event` and `github.create_release` reject direct execution
  without an approved Action context and idempotency key.
- A recovered ambiguous external mutation enters `NEEDS_REVIEW`; it is never
  blindly retried.

These are capability adapters, not a second execution path. Orchestrators and
future Workers invoke them only through `SharedTurnLoop` and the Trust Plane.
