# WeatherFlow v3 local hardening

WeatherFlow has no telemetry upload client. Durable Runs, events, derived
activity records, memory, and artifacts remain local. A diagnostic export is
created only after an explicit request, is written beneath the Workspace
internal root, redacts credential-like values, and records that no upload was
attempted.

ActivityWatch remains an independent, read-only raw fact source. WeatherFlow
does not own a watcher, heartbeat write path, or raw activity vault. Its
database contains only derived task/revision/statistics metadata and bounded
evidence references; raw titles, URLs, application names, AFK events, and
ActivityWatch-derived state inference are forbidden.

Recovery is conservative:

- retryable model failures receive bounded attempts and then pause;
- invalid checkpoints enter local quarantine and route the Run to review;
- startup audits non-terminal Runs but never silently replays side effects;
- unavailable provider tools are hidden from new capability snapshots;
- ambiguous external Actions remain in `NEEDS_REVIEW`.

Privacy controls separately preview and delete supported Workspace-owned data.
Deletion outranks append-only retention. Reset audit events retain category and
count only, never deleted content.

`make security-check` scans durable stores for credential values and forbidden
raw sensor fields. Findings expose only the table, row identifier, field, and
kind. `make check` runs this as a dedicated gate exactly once.
