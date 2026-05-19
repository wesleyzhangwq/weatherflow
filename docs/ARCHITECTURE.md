# WeatherFlow Architecture

WeatherFlow is a small explicit agent pipeline for developer rhythm, not a
general-purpose agent framework.

## System

```text
Next.js dashboard + wf CLI
          |
      FastAPI backend
          |
      Orchestrator
          |
 StateAgent -> ReflectionAgent -> PlanningAgent -> MemoryAgent
          |
 SQLite records + profile.md
          |
 DevReviewAgent <- GitHub MCP + Google Calendar MCP
```

## Inputs

WeatherFlow only trusts three product inputs:

- `check-in`: user-written state, work intention, blockers, and anxiety.
- `GitHub MCP`: PRs, issues, reviews, repositories, and public work activity.
- `Google Calendar MCP`: meeting load, event timing, focus windows, and collaboration pressure.

Local git, notes, workspace, and filesystem sensors were removed. This keeps the
product smaller, less invasive, and easier to explain.

## Daily Loop

1. User submits `POST /api/checkin`.
2. `StateAgent` estimates `UserStateOut` from check-in, recent check-ins,
   `profile.md`, and the latest Dev Review summary when available.
3. `ReflectionAgent` writes a short reflection with grounding sources.
4. `PlanningAgent` writes one next-step suggestion.
5. `MemoryAgent` refreshes `profile.md` from recent check-ins, reflections,
   suggestion feedback, memory feedback, and latest Dev Review.

## Dev Review Loop

1. User runs `wf dev-review --days 7` or clicks Run in the dashboard.
2. Backend fetches provider contexts from GitHub and Google Calendar.
3. `DevReviewAgent` synthesizes a developer rhythm review.
4. The review is persisted with source coverage and run steps.
5. Future state, reflection, planning, and profile refreshes can use the latest
   review as work-rhythm context.

Dev Review is a core product capability: it is how WeatherFlow turns developer
activity and calendar load into evidence-backed rhythm awareness.

## Storage

SQLite stores operational records:

- `checkins`
- `reflections`
- `state_snapshots`
- `events` for suggestion/profile feedback
- `agent_runs`
- `dev_reviews`

Readable long-term memory lives in:

```text
DATA_DIR/memory/profile.md
```

There is no vector memory or hidden long-term store in the active architecture.
The profile is deliberately inspectable, editable, and diffable.

## Scheduler

The scheduler only runs:

- evening reflection
- weekly review

There is no background sensor sweep.

## API Surface

Primary routers:

- `/api/checkin`
- `/api/state`
- `/api/reflection`
- `/api/memory/profile`
- `/api/feedback`
- `/api/dev-review`
- `/api/mcp`

## Non-Goals

- Browser automation
- Local filesystem behavior monitoring
- Multi-agent swarms
- Opaque vector memory
- Generic task execution
