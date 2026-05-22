# WeatherFlow

> **A local-first developer rhythm companion.**

WeatherFlow helps developers understand their current work rhythm, protect momentum,
and recover from overload. It is not a general chatbot, browser agent, task runner, or
productivity boss. It is a small companion system that reads a few trusted signals and
turns them into state, reflection, memory, and one gentle next step.

## Product Shape

WeatherFlow has two core loops:

```text
Daily loop:
check-in -> StateAgent -> ReflectionAgent -> PlanningAgent -> profile.md

Developer rhythm loop:
GitHub MCP + Google Calendar MCP -> DevReviewAgent -> dashboard + profile context
```

Inputs are intentionally narrow:

- **User check-in** — the strongest signal for mood, focus, blockers, and intention.
- **GitHub MCP** — PRs, issues, reviews, repository activity, and shipping evidence.
- **Google Calendar MCP** — meeting load, focus windows, and collaboration pressure.

WeatherFlow does not run local git, notes, or workspace sensors. Dev Review is the
product's main evidence-backed work-rhythm feature, not a side module.

## What It Does

- Tracks life/work weather: Momentum, Recovery, Confusion, Overload, Burnout.
- Produces short daily and weekly reflections in a gentle voice.
- Maintains one readable long-term profile at `DATA_DIR/memory/profile.md`.
- Runs Dev Review from GitHub + Calendar evidence to summarize developer rhythm.
- Exposes a Next.js dashboard and `wf` CLI for low-friction daily use.
- Degrades locally with deterministic fallbacks when the LLM is unavailable.

## Architecture

```text
Next.js dashboard + wf CLI
          |
      FastAPI backend
          |
      Orchestrator
 State -> Reflection -> Planning -> Memory
          |
 SQLite records + profile.md
          |
 Dev Review providers: GitHub MCP + Google Calendar MCP
```

More detail lives in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
[docs/PHILOSOPHY.md](docs/PHILOSOPHY.md), and the
[Google Calendar setup guide](docs/GOOGLE_CALENDAR_SETUP.md).

## Quick Start

```bash
cp .env.example .env
# fill OPENAI_BASE_URL / OPENAI_API_KEY / models
make install

make dev-backend       # http://127.0.0.1:8765
make dev-frontend      # http://localhost:3000
```

CLI:

```bash
uv run wf checkin             # 1-3 minute check-in; runs the daily loop
uv run wf weather             # current weather/state
uv run wf reflect             # latest reflection, or --run to regenerate
uv run wf dev-review --days 7 # GitHub + Calendar developer rhythm review
uv run wf setup-calendar      # authorize Google Calendar for Dev Review
uv run wf dashboard           # open dashboard
```

Health checks:

```bash
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/api/meta/status
make check
```

Runtime data defaults to:

```text
${HOME}/.local/share/weatherflow/data
```

## Local-First Profile

WeatherFlow can run against any OpenAI-compatible endpoint. For local-only chat,
point `OPENAI_BASE_URL` at Ollama or another compatible local server. The durable
user model remains an editable Markdown file, not an opaque vector database.

## Engineering Principles

1. **Narrow inputs** — check-in, GitHub, and Calendar only.
2. **Dev rhythm first** — the product is about developer state and action cadence.
3. **Readable memory** — `profile.md` is the source of truth for long-term user modeling.
4. **Explicit orchestration** — no hidden agent swarm; the orchestrator is simple and inspectable.
5. **Gentle output** — one reflection and one next step, never a TODO flood.
