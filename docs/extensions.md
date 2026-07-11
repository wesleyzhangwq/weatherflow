# WeatherFlow v3 extensions

WeatherFlow installs Capability Packs, Skills, and Agent Definitions from one
versioned, digest-verified local package contract. An extension package is a
directory containing `manifest.json` and only the files named by that manifest.

## Trust boundary

- Manifests reject unknown fields, unsafe names, path traversal, duplicate
  files, symlinks, oversized files, and digest mismatches.
- Verified bytes are copied beneath the Workspace internal root and atomically
  renamed into a content-addressed directory.
- Workspace configuration stores the active immutable extension reference.
- Installing a Pack or Skill never grants scopes. Pack scopes and Skill tool
  IDs are descriptive requests only; Workspace policy remains authoritative.
- A model-driven `extensions.install` call has the `install` effect and cannot
  execute without an approved Action context.
- Agent Definitions and Skill text are loaded and frozen into the new parent
  Run checkpoint. Existing Runs never hot-switch prompts or definitions.
- Skills may guide decomposition but cannot add tools, scopes, or authority.

The public manifest kinds are `capability_pack`, `skill`, and
`agent_definition`, all at `schema_version: "1"`. Examples and the first-party
Developer, Research, Personal Operations, release Worker, and
minimum-burden-release packages live in `extensions/first-party/`.

## Credentials

Durable state contains only `CredentialRef(provider, name)`. A
`CredentialBroker` resolves the corresponding value from a process-local store
and passes it directly into an asynchronous provider transport callback. The
value is absent from the reference JSON and broker representation and must not
be returned through provider results, events, checkpoints, diagnostics, or
artifacts.
