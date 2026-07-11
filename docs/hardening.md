# WeatherFlow v3 local hardening

WeatherFlow does not contain a telemetry upload client. Run metrics are derived
locally from SQLite facts, and a diagnostic file is written only after the user
requests it. Private event payloads and credential-like values are redacted;
the export records `upload_attempted: false` and stays beneath the Workspace
internal root.

Privacy controls preview and independently reset behavior evidence, episodic
memory, profile assertions, artifacts, or all Workspace-owned content. Reset
audit events contain category and count only. Raw behavior expires after 72
hours and aggregate behavior after 90 days; audit facts are not expired by that
policy.

Recovery is deliberately conservative:

- retryable model failures receive three bounded attempts, then pause the Run;
- invalid checkpoints are content-addressed into a local quarantine and the Run
  enters `NEEDS_REVIEW`;
- startup audits non-terminal Runs but never silently executes them;
- unavailable provider tools are recorded and hidden from new Run snapshots;
- ambiguous external Actions remain governed by the existing review path.

The Cockpit shows local ownership, metadata-only behavior sensing, installed
Packs, retention, provider health, explicit diagnostic export, and a two-click
behavior-reset flow. The ambient companion remains silent and display-only.

`make security-check` exercises the durable-store scanner. It inspects events,
checkpoints and quarantine, memory/profile, Workspace configuration, and
artifact manifests for credential values and forbidden raw sensor fields. A
finding reports only table, row ID, field, and kind—not the detected content.
