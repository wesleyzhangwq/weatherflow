# WeatherFlow

> **An AI Companion for Long-term Human Growth**

WeatherFlow is **not** a chatbot, AI girlfriend, general-purpose assistant, AutoGPT, or browser agent.

It is a **long-term growth companion** — an external executive function that helps you maintain
your growth rhythm (your *flow*), understand your behavioral patterns, and find your way through
the seasons of your life.

> Modern people don't lack information. They suffer from **collapsed long-term growth order**.
> WeatherFlow exists to help you rebuild it.

## Core Metaphor: Life as Weather

Your life has weather. WeatherFlow does not try to *eliminate* bad weather.
It helps you understand it and walk through it.

```
Momentum   - shipping, in flow, things are moving
Recovery   - climbing back, momentum returning
Confusion  - direction unclear, motivation flat
Overload   - too much input, too many open loops, project switching high
Burnout    - drained, stress high, momentum collapsed
```

## What WeatherFlow Does

| Capability             | Priority |
| ---------------------- | -------- |
| Long-term Memory       | Critical |
| User Modeling          | Critical |
| Reflection             | Critical |
| State Tracking         | Critical |
| Behavior Analysis      | Critical |
| Gentle Planning        | High     |
| Tool Use / MCP         | Medium   |
| Browser Automation     | None     |

It is **memory-centric** and **reflection-first**, not tool-use centric.

## Daily Usage

- **Morning Check-in (1–3 min):** state, what you did, what's stuck, what you're anxious about.
- **Evening Reflection (auto):** the system summarizes, identifies patterns, updates your model.
- **Weekly Review (auto):** momentum trend, burnout risk, long-term behavioral patterns.

## Architecture

```
Next.js dashboard  +  wf CLI (check-in, sensors, start/stop)
         |                    |
         +----------+---------+
                    |
              FastAPI backend
                    |
              Orchestrator
    State · Reflection · Planning · Memory agents
                    |
         Hybrid memory (short-term events + buffer,
         mid-term Markdown vault, long-term Qdrant or SQLite vectors)
                    |
         SQLite + FTS5 + episodic / semantic / timeline / sensor tables
                    |
         Optional: scheduler (evening + weekly + sensor sweep)
                    |
CLI sensors: git, notes, workspace  |  MCP: GitHub, Google Calendar
```

Details:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
[docs/PHILOSOPHY.md](docs/PHILOSOPHY.md),
[docs/AGENT_WORKFLOW.md](docs/AGENT_WORKFLOW.md), and
[docs/REVIEW_CHECKLIST.md](docs/REVIEW_CHECKLIST.md).
Frontend upgrade notes live in
[docs/NEXT_UPGRADE_PLAN.md](docs/NEXT_UPGRADE_PLAN.md).

## Quick Start

```bash
# 1. Install dependencies
cp .env.example .env
# fill OPENAI_BASE_URL / OPENAI_API_KEY / models
make install

# 2. Backend and frontend
make dev-backend       # http://127.0.0.1:8765
make dev-frontend      # http://localhost:3000

# 3. CLI
uv run wf checkin             # interactive 1–3 min morning check-in
uv run wf weather             # current life weather
uv run wf reflect             # today's reflection
uv run wf setup-calendar --credentials ./credentials.json
uv run wf dev-review --days 7 # development rhythm review from GitHub + Calendar
uv run wf dev-review --latest # latest saved dev review
uv run wf patterns            # window-vs-window deterministic pattern report
uv run wf scan-git       --root ~/Projects     # behavior sensor
uv run wf scan-notes     --root ~/Notes        # notes / Obsidian sensor
uv run wf scan-workspace --root ~/Projects     # filesystem / fragmentation sensor
uv run wf sensors             # git + notes + workspace (one request)
```

Docker Compose can start backend, frontend, and Qdrant together:

```bash
docker compose up --build
```

### Health and checks

```bash
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/api/meta/status
make check
make inspect
```

`/api/meta/status` reports local runtime diagnostics without exposing secrets:
database path, Markdown memory path, scheduler jobs, configured models, and
whether long-term memory is using Qdrant or SQLite fallback.

By default, local runtime data lives outside the source tree:

```text
${HOME}/.local/share/weatherflow/data
```

### Local-first profile (no API key, no network)

WeatherFlow can run fully offline through Ollama:

```bash
brew install ollama
ollama serve &
ollama pull qwen2.5:7b
ollama pull bge-m3
cp .env.example.ollama .env
uvicorn app.main:app --reload --port 8765
```

The same OpenAI-compatible client is used; you just point `OPENAI_BASE_URL`
at `http://127.0.0.1:11434/v1`. See `.env.example.ollama`.

### Dev Review Agent

The Dev Review Agent is a manually triggered agent run. It uses configured
GitHub and Google Calendar providers to generate a structured development rhythm
review, stores the user-facing review, and keeps a lightweight execution trace
for provider coverage and failures.

Calendar storage keeps event titles, start times, durations, calendar names, and
derived categories. It does not store descriptions, attendee emails, meeting
links, locations, or attachments.

Google Calendar setup is local-first. Enable the Google Calendar API in Google
Cloud, create an OAuth Desktop client, download its `credentials.json`, then run:

```bash
uv run wf setup-calendar --credentials ./credentials.json
```

The command opens a browser consent flow and saves a refreshable token JSON under
`DATA_DIR` by default. The backend prefers `GOOGLE_CALENDAR_TOKEN_FILE` when it
exists and only uses `GOOGLE_CALENDAR_ACCESS_TOKEN` as a temporary fallback.

### Auto reflections

Evening reflection (default 22:00) and weekly review (default Sunday 21:00)
run on their own — that is the point of a "low-friction companion". Edit
`EVENING_REFLECTION_CRON` / `WEEKLY_REVIEW_CRON` in `.env` or set
`SCHEDULER_ENABLED=false` to disable.

## Engineering Principles

1. **Small but Deep** — few files, clear structure, restrained features.
2. **Local-first** — everything runs locally; no SaaS dependency.
3. **Memory-centric** — memory is the soul, not tool-use.
4. **Reflection-first** — reflection matters more than execution.
5. **Human-centric** — understand the human, don't automate everything.

## Working With Coding Agents

WeatherFlow can be built with coding agents, but agent work must stay bounded
and reviewable. Use [docs/AGENT_WORKFLOW.md](docs/AGENT_WORKFLOW.md) before
asking an agent to implement a feature, and use
[docs/REVIEW_CHECKLIST.md](docs/REVIEW_CHECKLIST.md) before accepting generated
code.

## Vision

In an age of information overload and attention collapse, WeatherFlow exists to help humans
**rebuild long-term growth order** — to understand themselves, maintain their rhythm, walk through
burnout, sustain flow, and become who they actually want to become.
