# Dev Review Agent Run Design

Date: 2026-05-17

## Goal

WeatherFlow should grow into a portfolio-quality agent development project
without becoming a generic automation agent. The first mature agent capability
will be a manually triggered **Dev Review Agent Run**: a development rhythm
review powered by high-value personal context sources.

The first version will use:

- GitHub MCP context for development output and collaboration signals.
- Google Calendar MCP context for meeting load and focus-window signals.

It will not use local sensors. The existing sensor approach produces signals
that are too shallow for this feature, such as file changes or repo switching,
and can easily misread real development work.

## Non-goals

- Do not build a general workflow engine.
- Do not build a skill marketplace.
- Do not add broad browser automation.
- Do not infer the user's psychological or physical energy from GitHub or
  Calendar data.
- Do not save full raw provider payloads.
- Do not implement Feishu or WeChat in the first version.

## Product Shape

The first version supports one fixed run type:

```text
dev_review
```

The user triggers it manually from the CLI or dashboard. WeatherFlow collects
provider summaries, synthesizes a structured development review, and stores a
lightweight execution trace.

High-level flow:

```text
CLI / Dashboard
  -> POST /api/dev-review/runs
  -> DevReviewAgent
  -> GitHub MCP + Google Calendar MCP
  -> normalized provider context
  -> structured DevReview
  -> saved review + AgentRun trace
  -> CLI / Dashboard display
```

## Core Concepts

### DevReview

`DevReview` is the user-facing result. It should be clear, stable, and useful
without exposing raw provider data.

Fields:

- `summary`: concise narrative summary of the review window.
- `dev_weather`: one development rhythm label:
  - `Deep Work`
  - `Shipping`
  - `Collaboration Heavy`
  - `Fragmented`
  - `Blocked`
- `main_work_threads`: 1-5 main work threads found in GitHub and Calendar.
- `shipping_progress`: concrete progress such as merged PRs, reviewed PRs,
  touched issues, and active work.
- `collaboration_load`: review loops, waiting states, issue discussions, and
  other collaboration pressure.
- `meeting_load`: meeting count, meeting hours, focus blocks, and notable event
  titles.
- `rhythm_risks`: evidence-backed risks that combine blockers and context
  switching risk.
- `next_week_suggestion`: one small suggestion for the next week.
- `source_coverage`: which providers were used, skipped, partial, or failed.

`dev_weather` describes the development rhythm only. It must not claim to know
the user's emotional, physical, or mental state.

### AgentRun

`AgentRun` is the execution record. It should make the run auditable without
turning the product UI into a tool-call transcript.

It records:

- run type
- status: `running`, `success`, `partial`, or `failed`
- start and finish timestamps
- input parameters
- provider readiness
- step outcomes
- warning and error summaries

This is what lets WeatherFlow show a mature agent execution lifecycle rather
than a single prompt wrapper.

## Backend Components

### `backend/app/agents/dev_review_agent.py`

Creates the structured review from normalized provider context. It is a fixed
purpose agent, not a free-form planner.

Responsibilities:

- Accept GitHub and Google Calendar normalized summaries.
- Include recent WeatherFlow profile or reflection context if useful.
- Produce schema-validated `DevReview` JSON.
- Fall back to deterministic synthesis when the LLM is unavailable.

### `backend/app/core/agent_runs.py`

Small execution runtime for `dev_review`.

Responsibilities:

- Create a run.
- Append provider and synthesis steps.
- Mark runs as `success`, `partial`, or `failed`.
- Keep the representation narrow enough that it does not become a generic
  workflow engine.

### `backend/app/memory/dev_review_repo.py`

Persists `DevReview` results and lightweight `AgentRun` traces.

The first version should use SQLite tables. It should not write every review
directly into long-term vector memory. A later weekly loop can decide whether a
review should update the profile.

### `backend/app/routers/dev_review.py`

API endpoints:

```text
POST /api/dev-review/runs
GET  /api/dev-review/runs/latest
GET  /api/dev-review/runs/{id}
```

The first endpoint triggers a run. The read endpoints return the user-facing
review plus lightweight trace and source coverage.

### CLI

Add a new CLI command:

```bash
uv run wf dev-review --days 7
uv run wf dev-review --days 14
uv run wf dev-review --latest
```

The CLI should print the review in a concise structure and include source
coverage and warnings when the run is partial.

### Dashboard

Add a simple Dev Review panel:

- latest `dev_weather`
- summary
- next week suggestion
- source coverage
- `Run Dev Review` button
- collapsible lightweight trace: GitHub, Calendar, LLM status

The first version should not include complex history charts or provider
configuration UI. Provider configuration can remain in environment variables.

## Data Model

Use two tables because the product result and execution trace serve different
readers.

### `agent_runs`

Execution audit table.

Suggested columns:

- `id`
- `run_type`
- `status`
- `started_at`
- `finished_at`
- `input_json`
- `steps_json`
- `error`

Used for:

- showing which providers were called
- debugging provider or LLM failures
- supporting future scheduled runs
- demonstrating a real agent execution lifecycle

### `dev_reviews`

User-facing result table.

Suggested columns:

- `id`
- `run_id`
- `window_days`
- `summary`
- `dev_weather`
- `main_work_threads_json`
- `shipping_progress_json`
- `collaboration_load_json`
- `meeting_load_json`
- `rhythm_risks_json`
- `next_week_suggestion`
- `source_coverage_json`
- `created_at`

Used for:

- CLI output
- dashboard latest review
- historical review lookup
- future weekly reflection/profile updates

## Provider Context

Each provider should return normalized context:

```json
{
  "source": "github",
  "status": "success",
  "window_days": 7,
  "signals": {},
  "coverage": {},
  "warnings": []
}
```

The `DevReviewAgent` should consume normalized context, not provider-specific
raw responses.

### GitHub MCP

GitHub context should summarize:

- touched repositories
- PRs opened, merged, reviewed, or waiting
- issues touched
- CI failures or unresolved review states
- collaboration load

The first version can start from the existing GitHub MCP summary and expand the
connector as needed.

### Google Calendar MCP

Google Calendar context should summarize:

- meeting count
- meeting hours
- focus blocks
- recurring meetings
- after-hours events
- notable event titles
- context fragmentation by day

Calendar persistence policy:

Save:

- event title
- start time
- duration
- calendar name
- derived category

Do not save:

- event description
- attendee emails
- meeting links
- location
- attachments

The review may cite event titles when they make the analysis more specific.

## Run Lifecycle

1. Create `agent_runs` row with status `running`.
2. Check GitHub and Google Calendar readiness.
3. Call ready providers.
4. Normalize provider context.
5. If no provider succeeds, mark run `failed` and do not create a review.
6. Synthesize `DevReview`.
7. Save `dev_reviews`.
8. Mark run `success` if all expected providers succeeded, otherwise `partial`.

## Degradation Strategy

- GitHub succeeds and Calendar is unavailable: generate a development-output
  and collaboration-focused review; mark Calendar missing.
- Calendar succeeds and GitHub is unavailable: generate a meeting-load and
  rhythm-focused review; mark GitHub missing.
- Both providers are unavailable: fail the run and ask the user to configure at
  least one provider.
- A provider call fails after readiness passed: mark the run partial and
  continue with successful providers.
- LLM synthesis fails: create a deterministic fallback review from normalized
  provider signals.
- Storage fails: mark the run failed and return an error. Do not pretend the
  review exists if it cannot be persisted.

`partial` is a first-class state. Real agent systems must preserve evidence and
continue when some tool calls fail.

## Testing Scope

Backend tests:

- provider readiness with configured and missing providers
- run lifecycle success, partial, and failed
- no review created when both providers are unavailable
- partial review created when only one provider succeeds
- `DevReview` schema validation
- deterministic fallback when LLM synthesis fails
- Google Calendar event titles are saved
- Calendar descriptions, attendees, meeting links, locations, and attachments
  are not saved

CLI tests:

- `wf dev-review --days 7` triggers a run and prints a review
- `wf dev-review --latest` prints the latest saved review
- partial runs show source coverage and warnings

Frontend tests:

- Dev Review panel renders latest review
- Run button triggers a new review and refreshes the panel
- partial source coverage is visible without dominating the UI

## Implementation Order

1. Backend persistence and schemas.
2. Agent run lifecycle.
3. GitHub and Google Calendar provider normalization.
4. DevReviewAgent synthesis and fallback.
5. API endpoints.
6. CLI command.
7. Dashboard panel.
8. Focused tests, then full `make check`.

## Open Constraints

- OAuth/token setup for Google Calendar should be kept minimal in the first
  version and documented clearly.
- The first version should prefer provider summaries over raw payload storage.
- Feishu and WeChat can be added later as providers using the same normalized
  context contract.
