# Review Checklist

This checklist is for reviewing code produced by a coding agent. You do not need
to understand every line on the first pass. Review from the outside in.

## 1. Scope

Start with the file list.

- Are the changed files related to the request?
- Did the agent touch generated files, local data, virtual environments, or
  unrelated modules?
- Did the change add a new directory or abstraction that the request did not
  obviously need?
- Is there any drive-by cleanup mixed into the feature?

If the scope feels too large, stop and ask the agent to split the change.

## 2. Entrypoint

Find where the behavior begins.

- Backend: router endpoint, scheduler job, CLI API call, or orchestrator method.
- Frontend: page, component, hook, or API helper.
- CLI: Typer command and backend request.
- Storage: repository method and schema/table.

You should be able to describe the flow in one sentence:

```text
User action -> API/CLI entrypoint -> model/schema -> core logic -> persistence -> response/UI
```

If that sentence is hard to write, the code is probably too tangled.

## 3. Data Shape

Review data before logic.

- Are request/response schemas explicit?
- Are TypeScript types aligned with Pydantic models?
- Are optional fields truly optional?
- Are defaults safe?
- Are timestamps, IDs, tags, and session IDs handled consistently?
- Does any field contain raw user content that should stay local?

Bad data shapes are expensive to fix later. Be strict here.

## 4. Fit With Existing Patterns

WeatherFlow already has clear patterns:

- FastAPI routers under `backend/app/routers/`
- repository modules under `backend/app/memory/`
- agents under `backend/app/agents/`
- deterministic sensors under `backend/app/sensors/`
- frontend API calls in `frontend/lib/api.ts`
- reusable dashboard components under `frontend/components/`
- CLI command modules under `cli/weatherflow_cli/`

Check:

- Does the new code live next to similar code?
- Does it use the same naming style?
- Does it reuse existing repositories, schemas, prompts, and helpers?
- Did it create a new "manager", "service", or "utils" file without a strong
  reason?

## 5. Simplicity

Ask these questions:

- Could this be fewer files?
- Could this be a normal function instead of a class?
- Could this reuse an existing repository method?
- Is a new abstraction used in at least two real places?
- Is the agent solving a future problem that does not exist yet?

Delete cleverness before it becomes load-bearing.

## 6. Error Handling

WeatherFlow should degrade gently, but not silently.

- Does a failed LLM call have a deterministic fallback where needed?
- Are failures logged when memory extraction, embedding, Qdrant, scheduler, or
  sensor work fails?
- Does user-facing code show a useful error instead of crashing?
- Does the code avoid swallowing exceptions that hide data loss?

Silent failure is especially dangerous in memory systems because the user may
only notice weeks later.

## 7. Tests

Tests should explain the behavior.

- Is there a focused backend test for new agent/router/repository behavior?
- Does the test cover fallback behavior, not only the happy path?
- If frontend changed, do `npm run lint` and `npm run build` pass?
- If CLI changed, is there at least a smoke path or mocked API test?
- Did the agent update snapshots or generated files without explaining why?

Use `make check` before accepting a completed change.

## 8. Product Voice

WeatherFlow is not a task boss.

- Does user-facing copy stay gentle and non-preachy?
- Does the suggestion avoid turning into a TODO list?
- Does the feature support memory, reflection, state, or behavioral insight?
- Does it avoid pushing the user toward more automation for its own sake?

If the feature feels like a generic productivity dashboard, reconsider it.

## 9. Local-First Boundary

Check privacy and environment impact.

- Does raw personal content stay local unless explicitly configured otherwise?
- Are paths, notes, and Git activity aggregated before being sent to an LLM?
- Does a new integration require a token or network call?
- Are secrets kept out of logs and diagnostics?
- Are `.env.example` and docs updated if configuration changed?

## 10. Final Review Prompt

Before accepting agent work, ask:

```text
Review your own change as a code reviewer.
Prioritize bugs, over-abstraction, duplicated logic, missing tests,
silent failures, and places that do not match existing project style.
List only issues and residual risks.
```

Then ask for a map:

```text
Explain this change as:
1. Entrypoint
2. Data shape
3. Core logic
4. Persistence
5. UI/CLI surface
6. Tests
7. Remaining risks
```

If the agent cannot explain the change clearly, the code is not ready.

## Acceptance Bar

Accept the change only when:

- The scope is understandable.
- The data shape is explicit.
- The implementation follows existing patterns.
- The tests or checks match the risk.
- `make check` passes, or the failure is clearly unrelated and documented.
- The maintainer can explain the flow without rereading the whole diff.
