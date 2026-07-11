# WeatherFlow v3 P0–P4 final audit

| Contract | Evidence | Result |
|---|---|---|
| One durable execution path | `RuntimeContainer` → frozen snapshot → `SharedTurnLoop`; MCP server and desktop call it | pass |
| Human state changes strategy, not goal/authority | frozen RhythmPolicy tests and flagship trajectory | pass |
| External mutations require approval | Trust Plane, Action idempotency, Calendar/GitHub/MCP tests | pass |
| Workers are bounded leaves | maximum three Workers, frozen definitions/skills, no recursive delegation | pass |
| Memory is source-linked context only | real local event validation, editable versioned assertions, rebuildable index, frozen tool-surface test | pass |
| Privacy is local and resettable | metadata-only schema, retention/reset APIs, redacted explicit diagnostics, durable-store scan | pass |
| Recovery is conservative | bounded model retry/pause, checkpoint quarantine, startup audit, provider degradation | pass |
| Desktop remains calm | silent companion, pure-input capsule, explicit Cockpit and approval controls | pass |
| Distribution is self-contained | arm64 PyInstaller sidecar, supervised app smoke, app/DMG checksums and SBOM | pass |
| Public trust claim | Developer ID signing and Apple notarization | blocked only by user-held credentials |

Final unsigned/ad-hoc validation on 2026-07-12:

- core: 213 regular tests plus 1 dedicated eval;
- desktop: 10 tests, lint, typecheck, and production build;
- Rust: 5 tests, format check, and compile check;
- standalone daemon: authenticated health in a minimal environment;
- bundle: arm64 `.app`, supervised sidecar smoke, valid ad-hoc code seal;
- disk image: `hdiutil verify` valid and checksum manifest valid;
- security: dedicated durable-store gate green;
- publishing: not performed.

The only remaining release operation that requires the user is installing or
selecting Apple Developer credentials. No architecture, test, privacy, or
authority gate was weakened to compensate for their absence.
