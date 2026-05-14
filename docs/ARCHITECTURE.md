# WeatherFlow Architecture

## High-level Diagram

```
+---------------------------+      +-----------------------------+
| Next.js Dashboard         |      | wf CLI                      |
| (life weather + timeline) |      | (check-in + behavior sensors|
|                           |      |  + start/stop/dashboard)    |
+-------------+-------------+      +--------------+--------------+
              |                                   |
              +----------------+------------------+
                               |
                  +------------v-------------+
                  |   FastAPI Backend        |
                  |   (routers / lifespan)   |
                  +------------+-------------+
                               |
                  +------------v-------------+
                  |      Orchestrator        |
                  |  +-------+  +----------+ |
                  |  | State |  |Reflection| |
                  |  +-------+  +----------+ |
                  |  | Memory|  | Planning | |
                  |  +-------+  +----------+ |
                  +------------+-------------+
                               |
                  +------------v-------------+
                  |   Hybrid Memory System   |
                  |  short  : session buffer |
                  |         + events table   |
                  |  mid    : Markdown vault |
                  |         (daily / weekly  |
                  |          / profiles)     |
                  |  long   : Qdrant or      |
                  |         SQLite vectors   |
                  |  + episodic + FTS5       |
                  |  + semantic KV + state   |
                  |  + timeline + sensors    |
                  +------------+-------------+
                               |
                  +------------v-------------+
                  |  Scheduler (APScheduler) |
                  |  evening + weekly +      |
                  |  optional sensor sweep   |
                  +--------------------------+
```

## Data Flow: Daily Loop

1. User opens the dashboard or runs `wf checkin`.
2. CLI / FE posts to `POST /api/checkin` with `{status, did_today, stuck_on, anxiety}`.
3. The Orchestrator runs the four agents in order:
   - **State Agent** — recomputes `UserState` (focus / stress / burnout / momentum /
     confidence / motivation) and maps it to one of five *weather labels*
     (Momentum / Confusion / Burnout / Overload / Recovery). Falls back to a
     deterministic heuristic when the LLM is unavailable.
   - **Reflection Agent** — produces a daily reflection (gentle, non-preachy).
   - **Memory Agent** — extracts long-term semantic features, appends to the daily
     Markdown note, embeds the day's content into `episodic_memory`, and compresses
     stable patterns into the long-term vector store (Qdrant when configured,
     else `episodic_memory` rows tagged `source = ltm_pattern`).
   - **Planning Agent** — produces at most one gentle suggestion, using a hybrid
     memory bundle (session buffer + recent events + mid-term Markdown +
     long-term vector hits) as context.
4. Every step also appends to the short-term `events` table and the in-process
   `session_buffer`, so the next read path (`POST /api/memory/context`) returns
   a unified bundle.
5. The dashboard re-reads `GET /api/state/current`, `GET /api/state/trend`,
   `GET /api/reflection`, and `GET /api/timeline`.

The same Orchestrator drives the **weekly loop** (`weekly_loop`): weekly reflection,
weekly Markdown digest, long-term compression, and a profile refresh pass.

## Data Flow: Behavior Sensors

WeatherFlow ships three local sensors. They are deterministic, run on the user's
machine, and never send raw content off-device.

| CLI                        | Endpoint                       | Signal                                                    |
| -------------------------- | ------------------------------ | --------------------------------------------------------- |
| `wf scan-git`              | `POST /api/sensors/git`        | commit count, distinct repos, `switch_score` (project switching) |
| `wf scan-notes`            | `POST /api/sensors/notes`      | file / word counts, input-vs-output ratio, top topics     |
| `wf scan-workspace`        | `POST /api/sensors/workspace`  | active project count, touched paths, `fragmentation_score` |
| `wf sensors` (one-shot)    | `POST /api/sensors/sweep`      | runs all of the above and recomputes state once           |

Sensor rows are treated as weak signals. After ingest, the backend stores the
aggregate row and derives low-confidence hypotheses (for example, "project
switching may be up") instead of recomputing `UserState` immediately. Check-in
and reflection surfaces can ask the user to confirm or reject pending hypotheses.
Only confirmed or repeatedly observed hypotheses are allowed to influence state
or long-term memory. The scheduler can run the bundled sweep on a cron
(`SENSOR_SWEEP_*`) so the user does not have to think about it.

## Storage Layout

All persistent state lives in one SQLite file (`DATA_DIR/DB_FILENAME`,
WAL-mode), plus a Markdown vault for mid-term memory and an optional Qdrant
collection for long-term vectors.

| Table                   | Purpose                                                       |
| ----------------------- | ------------------------------------------------------------- |
| `checkins`              | raw morning check-ins                                         |
| `reflections`           | daily / weekly reflections + insights JSON                    |
| `state_snapshots`       | timeseries of `UserState` + weather label                     |
| `timeline_events`       | growth timeline (`milestone` / `phase` / `event`)             |
| `semantic_memory`       | long-term user-model KV (e.g. "evening efficiency low")       |
| `episodic_memory`       | recent events, body + embedding BLOB; also stores compressed long-term patterns (`source = ltm_pattern`) when Qdrant is not configured |
| `episodic_memory_fts`   | FTS5 mirror of `episodic_memory.content`                      |
| `events`                | short-term high-frequency event log (per `session_id`)        |
| `git_activity`          | per-window commit / switch metrics                            |
| `notes_activity`        | Markdown / Obsidian read-vs-write signal                      |
| `workspace_activity`    | directory activity + fragmentation                            |
| `sensor_hypotheses`     | weak interpretations from sensors, pending until confirmed or repeated |

**Mid-term memory** is a Markdown vault under `MEMORY_MARKDOWN_DIR`
(defaults to `DATA_DIR/memory`): a daily note per day, a rolling weekly digest,
and a small set of user-profile snippets refreshed on the weekly loop.

**Long-term memory** uses a Qdrant collection when `QDRANT_URL` is set
(`LTM_DEDUPE_THRESHOLD` controls cosine de-dup). Otherwise the same compressed
patterns are stored in `episodic_memory` with `source = ltm_pattern` and
retrieved via numpy cosine over the BLOB embeddings.

## Memory Read Path

`gather_memory_context` (in `backend/app/memory/context.py`) assembles a single
Markdown bundle that the Planning Agent (and any future "tell me what you know
about me" surface) consumes:

```
## Memory context (hybrid)
### Session buffer (recent)         <- in-process per session_id
### Recent SQLite events            <- events table
### Mid-term profiles (excerpt)     <- Markdown vault
### Today's daily note (excerpt)    <- Markdown vault
### Long-term patterns (vector …)   <- Qdrant or SQLite cosine
```

## LLM Layer

A single `LLMClient` abstraction in [backend/app/core/llm.py](../backend/app/core/llm.py).

- Default provider: **OpenAI-compatible** (any gateway via `OPENAI_BASE_URL`).
- Optional **split** for embeddings (`EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY`)
  so chat can use one vendor (e.g. DeepSeek) while embeddings use another
  (e.g. DashScope, Ollama `bge-m3`).
- Methods: `async chat(...)`, `async chat_json(...)`, `async embed(...)`,
  `async aclose()`.
- Per-task model routing via `CHAT_MODEL_STATE` / `_REFLECTION` / `_PLANNING` /
  `_MEMORY` (empty falls back to `CHAT_MODEL`).
- Anthropic adapter is a class stub — agents do not need to change when it is
  filled in.
- Fully **local-first**: point `OPENAI_BASE_URL` at
  `http://127.0.0.1:11434/v1` (Ollama) and the same code path runs offline.

## Scheduler

`backend/app/core/scheduler.py` wraps APScheduler with a deliberately tiny cron
grammar (`"22:00"` for daily, `"sun:21:00"` for weekly, empty / `"off"` to
disable). On startup, the FastAPI lifespan registers three jobs:

- **Evening reflection** — `Orchestrator.daily_loop()` at `EVENING_REFLECTION_CRON`.
- **Weekly review** — `Orchestrator.weekly_loop()` at `WEEKLY_REVIEW_CRON`.
- **Sensor sweep** (opt-in) — `run_sensor_sweep` + state refresh at
  `SENSOR_SWEEP_CRON` when `SENSOR_SWEEP_ENABLED=true`.

This is the engineering side of the "low-friction companionship" promise:
the user does not have to remember to reflect.

## MCP Connectors

Implemented connectors (`backend/app/routers/mcp.py`):

- **GitHub** — `POST /api/mcp/github/sync` summarises recent activity for the
  token in `GITHUB_TOKEN`.
- **Notes** — `POST /api/mcp/notes/sync` scans a Markdown / Obsidian vault on
  the server side and writes the same aggregate row as `/api/sensors/notes`.

`GET /api/mcp/providers` reports per-provider `ready` / `needs_config` so the
frontend can show what is wired up.

## What is *not* in MVP

- Browser automation
- Multi-agent swarms / fancy planners
- Multi-modal
- Auth / multi-user
- Rich charts (we use lightweight SVG only)
