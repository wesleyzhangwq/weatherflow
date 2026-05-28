# AGENTS.md — Read This First

> If you're an agent (Claude / GPT / Cursor / whoever) about to make changes to
> this codebase, read this **before** anything else. Skim takes 5 minutes;
> following it will save you (and the user) hours.

---

## The single source of truth

[**`weatherflow-architecture-v1.md`**](./weatherflow-architecture-v1.md) is the
authoritative product + architecture spec. Everything in code, in tests, in
README, in this file — derives from it.

> **Conflict rule**: if the code disagrees with `weatherflow-architecture-v1.md`,
> the doc wins and the code is wrong.
>
> Want to change a fundamental contract? **Edit the v1 doc first**, append an
> entry to its `决策变更记录`, then change the code to match. Do **not** silently
> drift code away from the doc.

Two companion docs that fill gaps the v1 doc left intentionally open:

- [`docs/ADR-001-v1-refactor.md`](./docs/ADR-001-v1-refactor.md) — 22 numbered
  decisions (D1–D23) where the spec left room. ULID format, retry/fallback,
  conversation_id ownership, profile template, scope choices, etc.
- [`docs/ADR-002-weather-label-semantics.md`](./docs/ADR-002-weather-label-semantics.md)
  — 1:1 weather↔label mapping + the "LLM may override when evidence contradicts"
  escape hatch.

---

## The mental model in 60 seconds

WeatherFlow is a **rhythm coach + daily cockpit** for developers — *not* a
chatbot, productivity stack, task runner, or AI life coach. (See Constitution
rules 1, 4, 5 in v1 §1.)

```
4 inputs                       6 outputs
─────────                      ──────────
T1 Check-in   ─┐               O1 Hypothesis cards (home, ≤ 3)
T2 Scheduled  ─┤  unified      O2 Chat SSE stream
T3 Calibration─┼─►generate_   ─►O3 Proposal cards
T4 Chat       ─┘  hypothesis() O4 L1 event rows
                               O5 DelayedMemoryWriter fires
                               (O6: proactive push — banned by Constitution rule 7)
```

### Three memory layers

| Layer | Where | Mutability |
|---|---|---|
| **L1** facts | SQLite `events` (one table, ULID-keyed) | **append-only** |
| **L2** working context | `EvidenceBundle` assembled per-request | not persisted |
| **L3** long-term picture | `profile.md` (6 fixed sections) | only via DelayedMemoryWriter (4-gate) |

Anything that's not L1 is **derived**. The card stack, "current state", recent
rhythm — all computed from L1 events. Don't add a `current_state` column.

### Hard contracts (these are not negotiable without doc edits)

| Rule | Enforced where |
|---|---|
| Every `hypothesis.evidence[]` item carries `source_event_id` that exists in the bundle | `app/agents/rhythm_agent.py::_parse` |
| `label` ∈ 6 fixed values | `Literal` in `app/memory/schemas.py` |
| `weather` ∈ 6 fixed values | same |
| `destructive` tools never reach the LLM (not even the schema) | `ToolRegistry.register` skips them |
| All `write` tool calls become Proposal events; user must explicitly confirm | `mcp_client/dispatcher.py::_dispatch_write` |
| L1 events are never updated/deleted; status of a hypothesis is *derived* from later feedback events | `app/memory/event_log.py` exposes no update/delete |
| Calibration does **not** generate a new hypothesis | `app/routers/hypotheses.py::submit_feedback` |
| Proposal generation is **only** in the Chat flow | check-in & T2 paths simply don't have a Dispatcher |

If you find yourself wanting to "loosen" any of these, **stop** — that's almost
always a sign you misread the doc.

---

## File map (what lives where)

```
backend/app/
  memory/
    event_log.py         ← L1: append, get, latest_by_type, find_refs
    schemas.py           ← pydantic models + Literal enums
    context_loader.py    ← L2: assembles EvidenceBundle per §6
    profile_md.py        ← L3: 6 sections, fcntl-locked writes
    hypotheses_view.py   ← derives card-stack state from L1 (ADR D15)
    delayed_writer.py    ← 4-gate maybe_update() (§9.2)
  agents/
    rhythm_agent.py      ← generates Hypothesis from EvidenceBundle (T1/T2/T4)
    chat_agent.py        ← T4 ReAct loop (function-calling, max 8 turns)
  core/
    orchestrator.py      ← THE generate_hypothesis() entry shared by all triggers
    scheduled_check.py   ← T2 6-hour pipeline
    evidence_summarizer.py ← T2 LLM summarizer (§8.3)
    scheduler.py         ← APScheduler wiring (fixed 0/6/12/18 + DMW 12h heartbeat)
    llm.py               ← OpenAI-compat client + chat_json() w/ <think>-strip
  mcp_client/
    client.py            ← stdio MCP client + env forwarding to subprocess
    tool_registry.py     ← three-mode registry (read/write/destructive)
    dispatcher.py        ← read→exec / write→Proposal / destructive→error
  providers/
    calendar.py          ← raw calendar_snapshot fetcher (T2)
    github.py            ← raw github_snapshot fetcher (T2)
  routers/
    checkin.py           hypotheses.py  chat.py
    actions.py (proposals)  profile.py  events.py  dashboard.py
  main.py                ← FastAPI app, lifespan, scheduler wiring

mcp_servers/             ← Calendar + GitHub MCP servers (stdio)
frontend/                ← Next.js: HypothesisStack + DataStrip + CurrentStateWidget
                           + AmbientFooter on home; /checkin /chat /profile pages

backend/tests/
  contracts/  ← schema + source_event_id + L1 invariants
  flows/      ← T1/T3 end-to-end via FastAPI TestClient
  memory/     ← card-stack derivation + DMW 4-gate
  tools/      ← Dispatcher read/write/destructive
```

---

## How to safely make a change

1. **Read the relevant section of `weatherflow-architecture-v1.md`** before
   touching code. Find the §X.Y that governs this area. If your change isn't
   covered, ask the user before guessing.
2. **Search ADR-001 / ADR-002** for related decisions. Don't undo a decision —
   if you must, add a new ADR with reasoning.
3. **Make the edit.**
4. **Run the loop**:
   ```bash
   # backend
   uv run --package weatherflow-backend --extra dev ruff check backend/app backend/tests cli/weatherflow_cli
   uv run --package weatherflow-backend --extra dev pytest backend/tests -q

   # frontend
   (cd frontend && npm run lint && npx tsc --noEmit && npm run build)
   ```
   Same checks CI runs. Don't push unless these are green.
5. **Add tests** in the matching subdirectory (`contracts/` / `flows/` /
   `memory/` / `tools/`).
6. **If you touched a contract** (schemas, public API, event types,
   constitution rule interpretation), append to ADR-001 OR write a new ADR.
7. **Don't proactively push or merge.** Wait for explicit user instruction.

---

## Anti-patterns (these were removed in the v1 refactor — don't reintroduce)

- ❌ A numeric "user state" snapshot (focus / stress / burnout / momentum /
  confidence / motivation). v1 replaced this with discrete hypothesis events.
- ❌ Per-agent LLM model routing (`CHAT_MODEL_STATE`, `CHAT_MODEL_REFLECTION`,
  etc.). v1 has ONE rhythm agent + ONE chat agent, both use `CHAT_MODEL`.
- ❌ Local file-system "sensors" (sensor_sweep_git_roots / notes_roots /
  workspace_roots). v1 Constitution rule 4: integrations are Calendar + GitHub
  only, this is a product line.
- ❌ Pattern detection engine (`core/patterns.py` with rolling-window stats).
  v1 derives patterns from confirmed hypotheses via DelayedMemoryWriter only.
- ❌ Reflection / Planning / DevReview / StateAgent. Subsumed by hypothesis +
  chat ReAct.
- ❌ A `dev_reviews` / `state_snapshots` / `reflections` / `checkins` table.
  L1 is one `events` table; everything else is derived.
- ❌ Qdrant or any vector DB. L3 is one editable Markdown file. Constitution
  rule 6: profile must stay human-readable & editable.
- ❌ Pre-existing-conversation auto-create on chat-page mount (the original
  bug). conversation_id is owned by the client, persists in localStorage.
- ❌ Direct (non-MCP) Google Calendar / GitHub connectors. v1 is MCP-only;
  direct mode was removed in this refactor (ADR D10).

---

## Reasoning-model gotchas

Default LLM in dev is often a reasoning model (MiniMax-M2, DeepSeek-R1, Qwen,
etc.). They emit `<think>...</think>` blocks **before** their real response,
even when `response_format=json_object` is set.

- `core/llm.py::chat_json` already strips them — use that for JSON-mode calls.
- `agents/chat_agent.py::_strip_think` strips them from function-calling
  `message.content` before logging to L1 / streaming to client.
- If you add a new LLM call that doesn't go through `chat_json`, **strip
  `<think>` yourself** or these leak into L1 forever (append-only).
- `max_tokens=4000` for any JSON-output call so the JSON tail isn't truncated
  by a long think block. Don't set it lower without checking.

---

## When something feels weird

- **State derivation looks wrong** → re-read v1 §4.5 + ADR D15.
- **Hypothesis card shows up multiple times** → check `_is_first_turn` in
  `routers/chat.py` and the conversation_id rules in v1 §5.5.
- **Tool stops working** → first check the env forwarding in
  `mcp_client/client.py::_forwarded_env`. MCP subprocesses don't inherit `.env`.
- **Profile.md not updating** → it's by design slow. The 4 gates in
  `delayed_writer.py` are intentionally strict (v1 §9.2).
- **Test fails with timing issues** → `event_log._now_iso()` uses microsecond
  precision for a reason; don't downgrade.

---

## Quick contact card

- Spec: `weatherflow-architecture-v1.md`
- Decisions: `docs/ADR-001-v1-refactor.md`, `docs/ADR-002-weather-label-semantics.md`
- Run the app: see [README.md](./README.md) Quick Start
- Calendar OAuth: `docs/GOOGLE_CALENDAR_SETUP.md`

If something here feels stale, **the user is the boss** — ask first, don't
just patch the doc to make the code look right.
