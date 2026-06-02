# AGENTS.md — Read This First

> If you're an agent (Claude / GPT / Cursor / whoever) about to make changes to
> this codebase, read this **before** anything else. Skim takes 5 minutes;
> following it will save you (and the user) hours.

---

## The single source of truth

[**`weatherflow-architecture-v2.md`**](./weatherflow-architecture-v2.md) is the
authoritative product + architecture spec for v2. Everything in code, in tests,
in README, in this file — derives from it.

> **Conflict rule**: if the code disagrees with `weatherflow-architecture-v2.md`,
> the doc wins and the code is wrong.
>
> Want to change a fundamental contract? **Edit the v2 doc first**, append an
> entry to its `决策变更记录`, then change the code to match. Do **not** silently
> drift code away from the doc.

v1 document is archived at [`weatherflow-architecture-v1.md`](./weatherflow-architecture-v1.md).

Three companion docs:

- [`docs/ADR-001-v1-refactor.md`](./docs/ADR-001-v1-refactor.md) — 22 numbered
  decisions (D1–D23) where the spec left room. ULID format, retry/fallback,
  conversation_id ownership, profile template, scope choices, etc.
- [`docs/ADR-002-weather-label-semantics.md`](./docs/ADR-002-weather-label-semantics.md)
  — 1:1 weather↔label mapping + the "LLM may override when evidence contradicts"
  escape hatch.
- [`docs/ADR-003-v2-pivot.md`](./docs/ADR-003-v2-pivot.md) — 10 v2 decisions:
  mem0 as derived layer, LangGraph multi-agent, calibrated proactivity,
  Provider SPI, observability, eval framework, and more.
- [`docs/ADR-004-v2-full-adoption.md`](./docs/ADR-004-v2-full-adoption.md) — full
  commitment to the v2 paradigm: graph is the **sole** execution path (no v1
  fallback), real HITL (`interrupt()` + `AsyncSqliteSaver`), one trace tree per
  run, `astream` streaming, and the FIV (Facts/Index/View) memory framing. The
  "serializable state vs live objects" discipline lives here.

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

### Four memory layers (v2)

| Layer | Where | Mutability |
|---|---|---|
| **L1** facts | SQLite `events` (one table, ULID-keyed) | **append-only** |
| **L2** working context | `EvidenceBundle` assembled per-request | not persisted |
| **L2.5** semantic recall | mem0 + Qdrant (v2) — L1's derived projection | rebuildable from L1 |
| **L3** long-term picture | `profile.md` (6 fixed sections) | only via DelayedMemoryWriter (4-gate) |

Anything that's not L1 is **derived**. L2.5 is a derived projection — delete
Qdrant and `rebuild_memory.py` can rebuild it from L1. The card stack, "current
state", recent rhythm — all computed from L1 events. Don't add a `current_state`
column.

> **FIV framing (ADR-004 D5)**: the four "layers" are really 3 roles over 2
> stores — **Facts** (L1, the only truth), **Index** (`retrieval.py`: a recency
> strategy over L1 + a semantic strategy over mem0), and **View** (`profile.md`).
> mem0 stores *episodic instances* (forgettable); profile.md stores *validated
> generalizations* (4-gate). They never write to each other. The derived layers
> are refreshed from **one** place: `derivations.run_derivations()`.

### Hard contracts (these are not negotiable without doc edits)

| Rule | Enforced where |
|---|---|
| Every `hypothesis.evidence[]` item carries `source_event_id` that exists in the bundle | `app/agents/rhythm_agent.py::_parse` + v2 critic node runtime check |
| `label` ∈ 6 fixed values | `Literal` in `app/memory/schemas.py` |
| `weather` ∈ 6 fixed values | same |
| `destructive` tools never reach the LLM (not even the schema) | `ToolRegistry.register` skips them |
| All `write` tool calls become Proposal events; user must explicitly confirm | LangGraph `interrupt()` in the act node + `AsyncSqliteSaver` checkpointer; resumed by `POST /api/actions/{id}/execute` (ADR-004 D2) |
| L1 events are never updated/deleted; status of a hypothesis is *derived* from later feedback events | `app/memory/event_log.py` exposes no update/delete |
| Calibration does **not** generate a new hypothesis | `app/routers/hypotheses.py::submit_feedback` |
| Proposal generation is **only** in the Chat flow | check-in & T2 paths simply don't have a Dispatcher |
| L2.5 (mem0) is a derived projection of L1, never a source of truth | `scripts/rebuild_memory.py` can rebuild from L1; every mem0 memory carries `source_event_id` |

If you find yourself wanting to "loosen" any of these, **stop** — that's almost
always a sign you misread the doc.

---

## File map (what lives where)

```
backend/app/
  memory/
    event_log.py         ← L1: append, get, latest_by_type, find_refs
    schemas.py           ← pydantic models + Literal enums
    context_loader.py    ← assembles EvidenceBundle (orchestrates the two retrieval strategies + budget)
    retrieval.py         ← v2: recall_recent (recency) + recall_semantic (mem0) strategies
    derivations.py       ← v2: run_derivations() fan-out → mem0 (L2.5) + profile.md (L3)
    profile_md.py        ← L3: 6 sections, fcntl-locked writes
    hypotheses_view.py   ← derives card-stack state from L1 (ADR D15)
    delayed_writer.py    ← 4-gate maybe_update() (§9.2)
    semantic/            ← v2: L2.5 mem0 layer
      projector.py       ← L1 → mem0 projection (driven by derivations.py fan-out)
      recall.py          ← mem0 semantic search (source_event_id back-links)
  agents/
    graph/               ← v2: LangGraph multi-agent (SOLE chat path, no v1 fallback)
      state.py           ← AgentState (TypedDict — serializable data only)
      chat_graph.py      ← load_context → recall → plan → act → human_review(interrupt) → criticize → synthesize
      rhythm_graph.py    ← T1/T2 subgraph: recall → hypothesize → verify → persist
      graph_runner.py    ← adapter: graph.astream → SSE; resume_chat() after proposal
    rhythm_agent.py      ← generates Hypothesis from EvidenceBundle (T1/T2/T4)
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
  providers/             ← v2: Provider SPI
    base.py              ← Provider protocol
    calendar.py          ← raw calendar_snapshot fetcher (T2)
    github.py            ← raw github_snapshot fetcher (T2)
  routers/
    checkin.py           hypotheses.py  chat.py
    actions.py (proposals)  profile.py  events.py  dashboard.py
  main.py                ← FastAPI app, lifespan, scheduler wiring

backend/eval/            ← TORN DOWN (pending rebuild). The v1 eval framework
                           conflated static structural checks with live evals
                           and half its judges weren't wired to the real graph;
                           removed wholesale to rebuild against the v2 agent
                           architecture. History: see git + future ADR-005.

mcp_servers/             ← Calendar + GitHub MCP servers (stdio)
frontend/                ← Next.js: HypothesisStack + DataStrip + CurrentStateWidget
                           + AmbientFooter on home; /checkin /chat /profile pages
desktop/                 ← Phase 2: Electron + TS (桌面宠物卫星 App)

backend/tests/
  contracts/  ← schema + source_event_id + L1 invariants
  flows/      ← T1/T3 end-to-end via FastAPI TestClient
  memory/     ← card-stack derivation + DMW 4-gate
  tools/      ← Dispatcher read/write/destructive
  agents/     ← v2: LangGraph graph tests
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
  etc.). v2 multi-agent still uses ONE model (`CHAT_MODEL`) for all nodes.
- ❌ Local file-system "sensors" (sensor_sweep_git_roots / notes_roots /
  workspace_roots). v2 Constitution rule 4: integrations are curated via
  Provider SPI, not open-ended file scanning.
- ❌ Pattern detection engine (`core/patterns.py` with rolling-window stats).
  v1 derives patterns from confirmed hypotheses via DelayedMemoryWriter only.
- ❌ Reflection / Planning / DevReview / StateAgent. Subsumed by LangGraph
  graph nodes (plan/act/criticize/synthesize) in v2.
- ❌ A `dev_reviews` / `state_snapshots` / `reflections` / `checkins` table.
  L1 is one `events` table; everything else is derived.
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

- Spec: `weatherflow-architecture-v2.md` (v1 archived at `weatherflow-architecture-v1.md`)
- Decisions: `docs/ADR-001-v1-refactor.md`, `docs/ADR-002-weather-label-semantics.md`, `docs/ADR-003-v2-pivot.md`
- Run the app: see [README.md](./README.md) Quick Start
- Calendar OAuth: `docs/GOOGLE_CALENDAR_SETUP.md`

If something here feels stale, **the user is the boss** — ask first, don't
just patch the doc to make the code look right.
