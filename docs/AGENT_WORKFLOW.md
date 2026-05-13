# Coding Agent Workflow

WeatherFlow can be built with coding agents, but the agent is not the architect
of the project. Treat it as a fast pair-programmer: useful, tireless, and very
capable of making a mess if the boundaries are unclear.

The maintainer owns the shape of the system. The agent owns bounded execution.

## Default Rule

Do not ask an agent to "just implement it" until it has read the relevant code
and explained the smallest safe change.

Good first prompt:

```text
Do not edit code yet. Read the relevant modules and tell me:
1. Which files should this change touch?
2. What existing patterns should be reused?
3. What is the smallest implementation plan?
4. What are the main risks?
```

Only approve implementation after the answer is concrete and fits the current
architecture.

## Operating Mode

Use small, reviewable steps.

1. **Orient**
   - Read `README.md`, `docs/PHILOSOPHY.md`, and `docs/ARCHITECTURE.md` when the
     change touches product direction or system boundaries.
   - Read the target router, agent, repository, component, or CLI command before
     proposing edits.
   - Identify an existing similar implementation and reuse its style.

2. **Plan**
   - State the minimal file set.
   - State the data flow: entrypoint -> schema/type -> core logic -> storage/API
     -> UI/CLI.
   - State test coverage before writing code.
   - Call out new dependencies, migrations, background jobs, or environment
     changes before adding them.

3. **Implement**
   - Keep the change narrow.
   - Prefer existing modules over new directories.
   - Add a new abstraction only when it removes real duplication or matches an
     established local pattern.
   - Do not mix unrelated cleanup into feature work.
   - Preserve local data, virtual environments, generated artifacts, and user
     changes unless explicitly asked to clean them.

4. **Verify**
   - Run `make check` from the repo root.
   - If a narrower check is appropriate during iteration, run the focused command
     first, then finish with `make check`.
   - If a check cannot run, record the exact reason and the residual risk.

5. **Explain**
   - Summarize changed files and why they changed.
   - Explain the user-facing behavior.
   - List risks, tradeoffs, and follow-up work.
   - Do not bury failed checks.

## Step Boundaries

When a feature is more than a small patch, split it.

Good split:

```text
Step 1: backend schema/router/repository + tests.
Step 2: agent/orchestrator behavior + tests.
Step 3: frontend or CLI surface + build/lint.
```

Avoid one-pass changes that touch backend, frontend, CLI, scheduler, storage,
and prompts at once. That is how a project becomes difficult to review.

## Architecture Guardrails

WeatherFlow is memory-centric and reflection-first. New code should protect that
identity.

- Do not turn WeatherFlow into a general task automation agent.
- Do not add browser automation or broad tool-use loops unless the project
  direction explicitly changes.
- Keep reflections gentle and non-preachy.
- Keep sensors deterministic and local-first.
- Keep user memory inspectable and correctable where possible.
- Prefer explicit data flow over hidden magic.

## Dependency Rules

Adding a dependency is an architectural decision.

Before adding one, the agent must explain:

- What problem it solves.
- Why the standard library or existing dependency is not enough.
- Whether it affects local-first usage.
- Whether it changes install, Docker, or CI behavior.
- How it will be tested.

For frontend dependencies, update `package.json` and `package-lock.json`.
For Python dependencies, update the relevant `pyproject.toml`.

## Environment Rules

Source code and virtual environments are separate.

Commit-worthy project assets:

- `backend/pyproject.toml`
- `cli/pyproject.toml`
- `frontend/package.json`
- `frontend/package-lock.json`
- source files, tests, docs, scripts, examples

Local runtime artifacts:

- `backend/.venv/`
- `cli/.venv/`
- `frontend/node_modules/`
- `frontend/.next/`
- `backend/data/*.db`
- `backend/data/qdrant/`
- `backend/data/memory/`
- `__pycache__/`, `*.pyc`, egg-info

Agents should not delete local runtime artifacts unless the maintainer explicitly
asks for cleanup.

## Required Final Shape

Every completed agent task should end with:

```text
Changed:
- path: why it changed

Verified:
- command: result

Risks:
- anything still uncertain
```

The goal is not to produce more code. The goal is to keep WeatherFlow coherent
while it grows.
