# Dev Review History and Evidence Design

## Goal

Make Dev Review feel like an auditable agent workflow rather than a one-off
summary generator. Users should be able to see recent Dev Review runs, compare
their statuses and weather labels, and inspect provider coverage without running
a new review.

## Scope

This iteration adds a small history surface over existing persisted
`dev_reviews` and `agent_runs` data.

Included:

- Backend endpoint: `GET /api/dev-review/runs?limit=5`
- CLI option: `wf dev-review --history`
- Dashboard history list inside the existing Dev Review panel
- Tests for backend and CLI-facing formatting behavior

Not included:

- Editing or deleting reviews
- Charts or trend analytics
- New provider types
- Commitment tracking or follow-up scoring

## Product Behavior

The Dev Review panel should still lead with the latest review. Below the main
summary, it should show a compact list of recent runs. Each item should show:

- created time
- `dev_weather`
- run status
- provider coverage summary, for example `github: success · google_calendar: skipped`

The CLI should support:

```bash
uv run wf dev-review --history
```

It prints the same compact history. If there are no saved reviews, it says so.

## Backend Design

`dev_review_repo` already persists reviews with their associated run records.
Add `list_reviews(limit: int = 5) -> list[DevReviewRecord]`, ordered by
`created_at DESC, id DESC`.

Add a router endpoint:

```text
GET /api/dev-review/runs?limit=5
```

The limit is clamped by FastAPI validation to `1..20`. The response model is
`list[DevReviewRecord]`.

## Frontend Design

`frontend/lib/api.ts` gets `devReviewHistory(limit = 5)`.

`frontend/app/page.tsx` fetches history alongside the latest review and provider
readiness. The panel receives `history`.

`DevReviewPanel` keeps the current main card behavior and adds a compact
history section only when history exists. This is a dashboard/workbench surface,
so the UI should stay quiet and scannable.

## Error Handling

- Backend returns an empty list when no reviews exist.
- Frontend already uses `fetchOk`; history fetch failure becomes an empty list.
- CLI catches API errors through the existing command-level exception handling.

## Testing

Backend:

- Create two Dev Review records and assert `GET /api/dev-review/runs` returns
  newest first.
- Assert `limit=1` returns one item.

CLI:

- Add a pure formatter test for history output if the existing CLI test
  structure supports it. If not, keep the formatting logic deterministic and
  cover it through a small helper.

Frontend:

- TypeScript build should cover prop/type wiring.

## Success Criteria

- A user can inspect recent Dev Review runs without creating a new run.
- The feature uses existing persistence and does not introduce new schema.
- `make check` passes.
