# Provider Readiness UX Design

Date: 2026-05-18

## Goal

Make the Dev Review Agent demo-ready by showing provider readiness before a run
starts. The user should know whether GitHub and Google Calendar are configured,
which sources the next run can use, and why the run button may be disabled.

This is a polish sprint. It must not expand into OAuth, remote health checks, or
new providers.

## Non-goals

- Do not implement Google OAuth or refresh-token management.
- Do not call remote provider APIs from the dashboard readiness endpoint.
- Do not add Feishu, WeChat, browser automation, or local sensors.
- Do not redesign the whole dashboard.
- Do not change Dev Review synthesis behavior.

## Product Behavior

The Dev Review panel should show a compact readiness row:

- GitHub: `Ready` or `Needs config`
- Google Calendar: `Ready` or `Needs config`

The run button should be enabled when at least one provider is ready. It should
be disabled when neither provider is configured.

Empty states should be specific:

- If at least one provider is ready and no review exists, invite the user to run
  a Dev Review.
- If no provider is ready, tell the user to configure GitHub or Google Calendar
  first.

The existing source coverage and run-step details remain the place to inspect
what happened after a run.

## Backend API

Add a Dev Review specific readiness endpoint:

```text
GET /api/dev-review/providers
```

Response shape:

```json
[
  {
    "name": "github",
    "label": "GitHub",
    "status": "ready",
    "required_env": "GITHUB_TOKEN",
    "used_for": "PRs, issues, reviews, repository activity",
    "blocking": false
  },
  {
    "name": "google_calendar",
    "label": "Google Calendar",
    "status": "needs_config",
    "required_env": "GOOGLE_CALENDAR_ACCESS_TOKEN",
    "used_for": "meeting load, focus windows, calendar event titles",
    "blocking": false
  }
]
```

Rules:

- `ready`: required environment value is present and non-empty.
- `needs_config`: required environment value is empty.
- `blocking`: always `false` in the first version because a Dev Review can run
  with either provider. The UI decides whether the overall run is possible by
  checking whether at least one provider is ready.

No remote auth check is performed in this sprint. Auth failures still surface
during the actual run and are recorded in `AgentRun` trace and source coverage.

## CLI

Add:

```bash
uv run wf dev-review --check
```

Behavior:

- Fetch `/api/dev-review/providers`.
- Print each provider and status.
- Do not trigger a Dev Review run.
- Exit successfully even when providers need configuration.

Example:

```text
Dev Review Providers
- GitHub: ready (GITHUB_TOKEN)
- Google Calendar: needs_config (GOOGLE_CALENDAR_ACCESS_TOKEN)
```

## Frontend

Extend `DevReviewPanel` to accept provider readiness from the server-rendered
home page.

Add types and API helper:

- `DevReviewProviderStatus = "ready" | "needs_config"`
- `DevReviewProvider`
- `api.devReviewProviders()`

Home page fetches `/api/dev-review/providers` alongside the latest review and
passes it into the panel.

Panel changes:

- Show provider readiness badges or compact rows.
- Disable Run when no provider is ready.
- Keep Run enabled when one provider is ready.
- Show concise missing-config guidance when no provider is ready.

## Error Handling

- If the readiness endpoint fails in the dashboard SSR fetch, pass an empty list
  and keep the panel usable but conservative.
- If the panel has no readiness data, do not disable Run solely because the
  readiness fetch failed. The run endpoint remains the source of truth.
- If the CLI `--check` request fails because the backend is down, print the same
  existing `Dev review failed: ...` style error and exit 1.

## Testing Scope

Backend tests:

- no env values -> both providers `needs_config`
- GitHub token only -> GitHub `ready`, Calendar `needs_config`
- Calendar token only -> Calendar `ready`, GitHub `needs_config`
- both env values -> both `ready`

CLI tests or lightweight verification:

- `wf dev-review --check` shows both provider names and does not call the run
  endpoint.

Frontend checks:

- TypeScript build passes.
- Panel enables Run when at least one provider is ready.
- Panel disables Run and shows setup guidance when no provider is ready.

## Implementation Order

1. Backend schema/types for provider readiness and endpoint tests.
2. Backend endpoint in `backend/app/routers/dev_review.py`.
3. CLI `--check` support.
4. Frontend API types/helper and panel readiness UI.
5. Focused tests, then full `make check`.
