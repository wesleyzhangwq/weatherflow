# Dev Review Agent Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a manually triggered Dev Review Agent Run that uses GitHub and Google Calendar MCP-style context to produce a structured development rhythm review with an auditable execution trace.

**Architecture:** Add a narrow `dev_review` run path, not a generic workflow engine. Persist execution state in `agent_runs`, persist user-facing output in `dev_reviews`, normalize provider summaries before synthesis, and expose the result through FastAPI, `wf dev-review`, and a small dashboard panel.

**Tech Stack:** FastAPI, Pydantic, SQLite, httpx, Typer, Next.js App Router, TypeScript, existing WeatherFlow LLM client.

---

## File Map

- Create `backend/app/memory/dev_review_repo.py`: SQLite CRUD for `agent_runs` and `dev_reviews`.
- Modify `backend/app/memory/store.py`: add `agent_runs` and `dev_reviews` tables.
- Modify `backend/app/memory/schemas.py`: add Dev Review, Agent Run, provider context, and request/response models.
- Create `backend/app/core/agent_runs.py`: small lifecycle helper for creating runs and appending steps.
- Create `backend/app/mcp/google_calendar.py`: Google Calendar connector that returns sanitized event-title context.
- Modify `backend/app/mcp/github.py`: add a normalized provider context method while keeping existing behavior.
- Modify `backend/app/config.py`: add Google Calendar configuration.
- Create `backend/app/agents/dev_review_agent.py`: structured synthesis and deterministic fallback.
- Modify `backend/app/core/prompts.py`: add `DEV_REVIEW_SYSTEM`.
- Create `backend/app/routers/dev_review.py`: `POST /api/dev-review/runs`, `GET /latest`, `GET /{id}`.
- Modify `backend/app/main.py`: include the dev review router.
- Create `cli/weatherflow_cli/dev_review.py`: CLI command.
- Modify `cli/weatherflow_cli/__main__.py`: register `wf dev-review`.
- Modify `frontend/lib/api.ts`: add types and API helpers.
- Create `frontend/components/DevReviewPanel.tsx`: dashboard panel with run button.
- Modify `frontend/app/page.tsx`: fetch and render the panel.
- Add focused backend, CLI, and frontend tests listed below.

## Task 1: Persistence and Schemas

**Files:**
- Modify: `backend/app/memory/store.py`
- Modify: `backend/app/memory/schemas.py`
- Create: `backend/app/memory/dev_review_repo.py`
- Test: `backend/tests/test_dev_review_repo.py`

- [ ] **Step 1: Write failing repository tests**

Create `backend/tests/test_dev_review_repo.py`:

```python
from __future__ import annotations

from app.memory import dev_review_repo
from app.memory.schemas import (
    AgentRunCreate,
    AgentRunStep,
    DevReviewCreate,
)


def test_agent_run_lifecycle_and_latest_review():
    run_id = dev_review_repo.create_run(
        AgentRunCreate(
            run_type="dev_review",
            input={"window_days": 7, "providers": ["github", "google_calendar"]},
        )
    )

    dev_review_repo.append_step(
        run_id,
        AgentRunStep(
            name="github",
            status="success",
            summary="Fetched 3 GitHub signals.",
            metadata={"signal_count": 3},
        ),
    )
    dev_review_repo.finish_run(run_id, status="partial", error=None)

    review_id = dev_review_repo.create_review(
        DevReviewCreate(
            run_id=run_id,
            window_days=7,
            summary="This was a collaboration-heavy week.",
            dev_weather="Collaboration Heavy",
            main_work_threads=["WeatherFlow Dev Review"],
            shipping_progress=["Merged one PR"],
            collaboration_load=["Two review loops"],
            meeting_load=["8 meetings, 5.5 hours"],
            rhythm_risks=["Review loops competed with focus time"],
            next_week_suggestion="Protect one two-hour block before opening new review threads.",
            source_coverage={"github": "success", "google_calendar": "missing"},
        )
    )

    latest = dev_review_repo.latest_review()
    assert latest is not None
    assert latest.id == review_id
    assert latest.run.id == run_id
    assert latest.run.status == "partial"
    assert latest.run.steps[0].name == "github"
    assert latest.dev_weather == "Collaboration Heavy"
    assert latest.source_coverage["google_calendar"] == "missing"
```

- [ ] **Step 2: Run the failing repository test**

Run:

```bash
cd backend && uv run pytest tests/test_dev_review_repo.py -v
```

Expected: FAIL because `dev_review_repo` and schema classes do not exist.

- [ ] **Step 3: Add SQLite tables**

In `backend/app/memory/store.py`, append these table definitions to `_SCHEMA` after `sensor_hypotheses`:

```sql

CREATE TABLE IF NOT EXISTS agent_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type    TEXT    NOT NULL CHECK (run_type IN ('dev_review')),
    status      TEXT    NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running','success','partial','failed')),
    started_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    input_json  TEXT    NOT NULL DEFAULT '{}',
    steps_json  TEXT    NOT NULL DEFAULT '[]',
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_type_started ON agent_runs(run_type, started_at DESC);

CREATE TABLE IF NOT EXISTS dev_reviews (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                     INTEGER NOT NULL REFERENCES agent_runs(id),
    window_days                INTEGER NOT NULL DEFAULT 7,
    summary                    TEXT    NOT NULL,
    dev_weather                TEXT    NOT NULL CHECK (
        dev_weather IN ('Deep Work','Shipping','Collaboration Heavy','Fragmented','Blocked')
    ),
    main_work_threads_json     TEXT    NOT NULL DEFAULT '[]',
    shipping_progress_json     TEXT    NOT NULL DEFAULT '[]',
    collaboration_load_json    TEXT    NOT NULL DEFAULT '[]',
    meeting_load_json          TEXT    NOT NULL DEFAULT '[]',
    rhythm_risks_json          TEXT    NOT NULL DEFAULT '[]',
    next_week_suggestion       TEXT    NOT NULL,
    source_coverage_json       TEXT    NOT NULL DEFAULT '{}',
    created_at                 TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_dev_reviews_created ON dev_reviews(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dev_reviews_run ON dev_reviews(run_id);
```

- [ ] **Step 4: Add Pydantic models**

In `backend/app/memory/schemas.py`, add:

```python
DevWeather = Literal[
    "Deep Work",
    "Shipping",
    "Collaboration Heavy",
    "Fragmented",
    "Blocked",
]
RunStatus = Literal["running", "success", "partial", "failed"]
ProviderStatus = Literal["success", "partial", "failed", "skipped"]


class ProviderContext(BaseModel):
    source: str
    status: ProviderStatus
    window_days: int = 7
    signals: Dict[str, Any] = Field(default_factory=dict)
    coverage: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class AgentRunStep(BaseModel):
    name: str
    status: ProviderStatus
    summary: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentRunCreate(BaseModel):
    run_type: Literal["dev_review"] = "dev_review"
    input: Dict[str, Any] = Field(default_factory=dict)


class AgentRunRecord(BaseModel):
    id: int
    run_type: Literal["dev_review"]
    status: RunStatus
    started_at: str
    finished_at: Optional[str] = None
    input: Dict[str, Any] = Field(default_factory=dict)
    steps: List[AgentRunStep] = Field(default_factory=list)
    error: Optional[str] = None


class DevReviewCreate(BaseModel):
    run_id: int
    window_days: int = 7
    summary: str
    dev_weather: DevWeather
    main_work_threads: List[str] = Field(default_factory=list)
    shipping_progress: List[str] = Field(default_factory=list)
    collaboration_load: List[str] = Field(default_factory=list)
    meeting_load: List[str] = Field(default_factory=list)
    rhythm_risks: List[str] = Field(default_factory=list)
    next_week_suggestion: str
    source_coverage: Dict[str, Any] = Field(default_factory=dict)


class DevReviewRecord(DevReviewCreate):
    id: int
    created_at: str
    run: AgentRunRecord


class DevReviewRunRequest(BaseModel):
    window_days: int = Field(default=7, ge=1, le=31)
    providers: List[Literal["github", "google_calendar"]] = Field(
        default_factory=lambda: ["github", "google_calendar"]
    )
```

Add the new names to `__all__`.

- [ ] **Step 5: Implement repository helpers**

Create `backend/app/memory/dev_review_repo.py`:

```python
"""CRUD helpers for dev review runs and results."""

from __future__ import annotations

import json
from typing import Optional

from app.memory.schemas import (
    AgentRunCreate,
    AgentRunRecord,
    AgentRunStep,
    DevReviewCreate,
    DevReviewRecord,
    RunStatus,
)
from app.memory.store import get_conn


def _loads_obj(raw: str | None) -> dict:
    return json.loads(raw or "{}")


def _loads_list(raw: str | None) -> list:
    return json.loads(raw or "[]")


def create_run(payload: AgentRunCreate) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_runs (run_type, status, input_json, steps_json)
            VALUES (?, 'running', ?, '[]')
            """,
            (payload.run_type, json.dumps(payload.input, ensure_ascii=False)),
        )
        return int(cur.lastrowid)


def get_run(run_id: int) -> Optional[AgentRunRecord]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, run_type, status, started_at, finished_at, input_json, steps_json, error
            FROM agent_runs WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
    return _run_from_row(row) if row else None


def append_step(run_id: int, step: AgentRunStep) -> AgentRunRecord:
    run = get_run(run_id)
    if run is None:
        raise ValueError(f"agent run not found: {run_id}")
    steps = [s.model_dump() for s in run.steps]
    steps.append(step.model_dump())
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_runs SET steps_json = ? WHERE id = ?",
            (json.dumps(steps, ensure_ascii=False), run_id),
        )
    updated = get_run(run_id)
    assert updated is not None
    return updated


def finish_run(run_id: int, *, status: RunStatus, error: str | None = None) -> AgentRunRecord:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE agent_runs
            SET status = ?, error = ?, finished_at = datetime('now')
            WHERE id = ?
            """,
            (status, error, run_id),
        )
    updated = get_run(run_id)
    if updated is None:
        raise ValueError(f"agent run not found: {run_id}")
    return updated


def create_review(payload: DevReviewCreate) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO dev_reviews (
                run_id, window_days, summary, dev_weather,
                main_work_threads_json, shipping_progress_json,
                collaboration_load_json, meeting_load_json, rhythm_risks_json,
                next_week_suggestion, source_coverage_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.run_id,
                payload.window_days,
                payload.summary,
                payload.dev_weather,
                json.dumps(payload.main_work_threads, ensure_ascii=False),
                json.dumps(payload.shipping_progress, ensure_ascii=False),
                json.dumps(payload.collaboration_load, ensure_ascii=False),
                json.dumps(payload.meeting_load, ensure_ascii=False),
                json.dumps(payload.rhythm_risks, ensure_ascii=False),
                payload.next_week_suggestion,
                json.dumps(payload.source_coverage, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)


def get_review(review_id: int) -> Optional[DevReviewRecord]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM dev_reviews WHERE id = ?",
            (review_id,),
        ).fetchone()
    return _review_from_row(row) if row else None


def latest_review() -> Optional[DevReviewRecord]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM dev_reviews ORDER BY created_at DESC, id DESC LIMIT 1"
        ).fetchone()
    return _review_from_row(row) if row else None


def latest_review_for_run(run_id: int) -> Optional[DevReviewRecord]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM dev_reviews WHERE run_id = ? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    return _review_from_row(row) if row else None


def _run_from_row(row) -> AgentRunRecord:
    return AgentRunRecord(
        id=row["id"],
        run_type=row["run_type"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        input=_loads_obj(row["input_json"]),
        steps=[AgentRunStep(**item) for item in _loads_list(row["steps_json"])],
        error=row["error"],
    )


def _review_from_row(row) -> DevReviewRecord:
    run = get_run(int(row["run_id"]))
    if run is None:
        raise ValueError(f"agent run not found for review: {row['run_id']}")
    return DevReviewRecord(
        id=row["id"],
        run_id=row["run_id"],
        window_days=row["window_days"],
        summary=row["summary"],
        dev_weather=row["dev_weather"],
        main_work_threads=_loads_list(row["main_work_threads_json"]),
        shipping_progress=_loads_list(row["shipping_progress_json"]),
        collaboration_load=_loads_list(row["collaboration_load_json"]),
        meeting_load=_loads_list(row["meeting_load_json"]),
        rhythm_risks=_loads_list(row["rhythm_risks_json"]),
        next_week_suggestion=row["next_week_suggestion"],
        source_coverage=_loads_obj(row["source_coverage_json"]),
        created_at=row["created_at"],
        run=run,
    )


__all__ = [
    "create_run",
    "get_run",
    "append_step",
    "finish_run",
    "create_review",
    "get_review",
    "latest_review",
    "latest_review_for_run",
]
```

- [ ] **Step 6: Run repository tests**

Run:

```bash
cd backend && uv run pytest tests/test_dev_review_repo.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit persistence**

```bash
git add backend/app/memory/store.py backend/app/memory/schemas.py backend/app/memory/dev_review_repo.py backend/tests/test_dev_review_repo.py
git commit -m "feat: persist dev review agent runs"
```

## Task 2: Agent Run Lifecycle Helper

**Files:**
- Create: `backend/app/core/agent_runs.py`
- Test: `backend/tests/test_agent_runs.py`

- [ ] **Step 1: Write failing lifecycle tests**

Create `backend/tests/test_agent_runs.py`:

```python
from __future__ import annotations

from app.core.agent_runs import AgentRunTracker
from app.memory import dev_review_repo
from app.memory.schemas import AgentRunCreate


def test_tracker_marks_partial_when_any_step_is_not_success():
    run_id = dev_review_repo.create_run(
        AgentRunCreate(input={"window_days": 7, "providers": ["github", "google_calendar"]})
    )
    tracker = AgentRunTracker(run_id)

    tracker.step("github", "success", "GitHub ready.", {"signal_count": 4})
    tracker.step("google_calendar", "skipped", "Google Calendar missing.", {})
    run = tracker.finish()

    assert run.status == "partial"
    assert len(run.steps) == 2
    assert run.steps[1].status == "skipped"


def test_tracker_can_fail_run_with_error():
    run_id = dev_review_repo.create_run(AgentRunCreate(input={"window_days": 7}))
    tracker = AgentRunTracker(run_id)

    run = tracker.fail("No provider succeeded.")

    assert run.status == "failed"
    assert run.error == "No provider succeeded."
```

- [ ] **Step 2: Run the failing lifecycle tests**

Run:

```bash
cd backend && uv run pytest tests/test_agent_runs.py -v
```

Expected: FAIL because `app.core.agent_runs` does not exist.

- [ ] **Step 3: Implement `AgentRunTracker`**

Create `backend/app/core/agent_runs.py`:

```python
"""Small lifecycle helper for fixed-purpose agent runs."""

from __future__ import annotations

from typing import Any

from app.memory import dev_review_repo
from app.memory.schemas import AgentRunRecord, AgentRunStep, ProviderStatus


class AgentRunTracker:
    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        self._saw_partial = False

    def step(
        self,
        name: str,
        status: ProviderStatus,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AgentRunStep:
        if status != "success":
            self._saw_partial = True
        step = AgentRunStep(
            name=name,
            status=status,
            summary=summary,
            metadata=metadata or {},
        )
        dev_review_repo.append_step(self.run_id, step)
        return step

    def finish(self) -> AgentRunRecord:
        status = "partial" if self._saw_partial else "success"
        return dev_review_repo.finish_run(self.run_id, status=status)

    def fail(self, error: str) -> AgentRunRecord:
        return dev_review_repo.finish_run(self.run_id, status="failed", error=error)


__all__ = ["AgentRunTracker"]
```

- [ ] **Step 4: Run lifecycle tests**

Run:

```bash
cd backend && uv run pytest tests/test_agent_runs.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit lifecycle helper**

```bash
git add backend/app/core/agent_runs.py backend/tests/test_agent_runs.py
git commit -m "feat: add agent run lifecycle helper"
```

## Task 3: Provider Normalization

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/mcp/github.py`
- Create: `backend/app/mcp/google_calendar.py`
- Test: `backend/tests/test_dev_review_providers.py`

- [ ] **Step 1: Write failing provider tests**

Create `backend/tests/test_dev_review_providers.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.mcp.github import normalize_github_summary
from app.mcp.google_calendar import sanitize_calendar_events


def test_normalize_github_summary_maps_existing_connector_payload():
    ctx = normalize_github_summary(
        {
            "login": "octo",
            "window_days": 7,
            "events": 5,
            "by_type": {"PullRequestEvent": 2, "IssuesEvent": 1},
            "repos_touched": 2,
            "repo_list": ["owner/a", "owner/b"],
        },
        window_days=7,
    )

    assert ctx.source == "github"
    assert ctx.status == "success"
    assert ctx.signals["events"] == 5
    assert ctx.signals["repos"] == ["owner/a", "owner/b"]
    assert ctx.coverage["login"] == "octo"


def test_sanitize_calendar_events_keeps_titles_but_drops_private_fields():
    event = {
        "summary": "WeatherFlow architecture sync",
        "description": "private notes",
        "hangoutLink": "https://meet.google.com/abc",
        "location": "Home",
        "attendees": [{"email": "person@example.com"}],
        "start": {"dateTime": "2026-05-17T10:00:00+08:00"},
        "end": {"dateTime": "2026-05-17T11:00:00+08:00"},
        "organizer": {"email": "owner@example.com"},
    }

    sanitized = sanitize_calendar_events([event])

    assert sanitized[0]["title"] == "WeatherFlow architecture sync"
    assert sanitized[0]["duration_minutes"] == 60
    assert "description" not in sanitized[0]
    assert "attendees" not in sanitized[0]
    assert "hangoutLink" not in sanitized[0]
    assert "location" not in sanitized[0]


def test_sanitize_calendar_all_day_event_uses_title_and_zero_duration():
    event = {
        "summary": "Release day",
        "start": {"date": "2026-05-17"},
        "end": {"date": "2026-05-18"},
    }

    sanitized = sanitize_calendar_events([event])

    assert sanitized[0]["title"] == "Release day"
    assert sanitized[0]["start"] == "2026-05-17"
    assert sanitized[0]["duration_minutes"] == 0
```

- [ ] **Step 2: Run failing provider tests**

Run:

```bash
cd backend && uv run pytest tests/test_dev_review_providers.py -v
```

Expected: FAIL because provider normalization helpers do not exist.

- [ ] **Step 3: Add Google Calendar config**

In `backend/app/config.py`, add settings fields to the existing `Settings` model:

```python
google_calendar_access_token: str = Field(default="", alias="GOOGLE_CALENDAR_ACCESS_TOKEN")
google_calendar_calendar_id: str = Field(default="primary", alias="GOOGLE_CALENDAR_CALENDAR_ID")
google_calendar_base_url: str = Field(
    default="https://www.googleapis.com/calendar/v3",
    alias="GOOGLE_CALENDAR_BASE_URL",
)
```

- [ ] **Step 4: Add GitHub normalization**

In `backend/app/mcp/github.py`, add:

```python
from app.memory.schemas import ProviderContext


def normalize_github_summary(summary: dict[str, Any], *, window_days: int) -> ProviderContext:
    events = int(summary.get("events") or 0)
    repos = list(summary.get("repo_list") or [])
    by_type = dict(summary.get("by_type") or {})
    warnings: list[str] = []
    if events == 0:
        warnings.append("No recent GitHub events returned for this window.")
    return ProviderContext(
        source="github",
        status="success",
        window_days=window_days,
        signals={
            "login": summary.get("login"),
            "events": events,
            "event_types": by_type,
            "repos_touched": int(summary.get("repos_touched") or len(repos)),
            "repos": repos,
        },
        coverage={"login": summary.get("login"), "raw_event_count": events},
        warnings=warnings,
    )
```

Add `normalize_github_summary` to `__all__`.

- [ ] **Step 5: Implement Google Calendar connector**

Create `backend/app/mcp/google_calendar.py`:

```python
"""Google Calendar MCP-style connector for Dev Review context."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.mcp.base import MCPConnector
from app.memory.schemas import ProviderContext


class GoogleCalendarConnector(MCPConnector):
    name = "google_calendar"

    def __init__(
        self,
        access_token: str,
        *,
        calendar_id: str = "primary",
        base_url: str = "https://www.googleapis.com/calendar/v3",
    ) -> None:
        self.access_token = access_token
        self.calendar_id = calendar_id
        self.base_url = base_url.rstrip("/")

    async def health(self) -> dict[str, Any]:
        async with self._client() as client:
            r = await client.get(f"/calendars/{self.calendar_id}")
        return {
            "name": self.name,
            "status": "ok" if r.status_code == 200 else "auth_failed",
            "code": r.status_code,
        }

    async def fetch(self, *, days: int = 7, **_: Any) -> ProviderContext:
        now = datetime.now(timezone.utc)
        time_min = now - timedelta(days=days)
        async with self._client() as client:
            r = await client.get(
                f"/calendars/{self.calendar_id}/events",
                params={
                    "timeMin": time_min.isoformat(),
                    "timeMax": now.isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": 250,
                },
            )
            r.raise_for_status()
            payload = r.json()
        events = sanitize_calendar_events(payload.get("items") or [])
        meeting_minutes = sum(int(e.get("duration_minutes") or 0) for e in events)
        after_hours = [
            e for e in events
            if _hour_from_iso(str(e.get("start") or "")) is not None
            and (_hour_from_iso(str(e.get("start") or "")) < 9 or _hour_from_iso(str(e.get("start") or "")) >= 18)
        ]
        return ProviderContext(
            source=self.name,
            status="success",
            window_days=days,
            signals={
                "meeting_count": len(events),
                "meeting_hours": round(meeting_minutes / 60, 2),
                "after_hours_events": len(after_hours),
                "events": events,
            },
            coverage={"calendar_id": self.calendar_id, "event_count": len(events)},
            warnings=[],
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=httpx.Timeout(20.0, connect=10.0),
        )


def sanitize_calendar_events(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for item in items:
        start = (item.get("start") or {}).get("dateTime") or (item.get("start") or {}).get("date")
        end = (item.get("end") or {}).get("dateTime") or (item.get("end") or {}).get("date")
        sanitized.append(
            {
                "title": item.get("summary") or "(untitled)",
                "start": start,
                "duration_minutes": _duration_minutes(start, end),
                "calendar_name": item.get("organizer", {}).get("displayName") or "",
                "category": _category_for_title(item.get("summary") or ""),
            }
        )
    return sanitized


def _duration_minutes(start: str | None, end: str | None) -> int:
    if not start or not end or "T" not in start or "T" not in end:
        return 0
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, int((e - s).total_seconds() // 60))


def _hour_from_iso(value: str) -> int | None:
    if "T" not in value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).hour
    except ValueError:
        return None


def _category_for_title(title: str) -> str:
    lower = title.lower()
    if any(word in lower for word in ["review", "pr", "code"]):
        return "review"
    if any(word in lower for word in ["sync", "standup", "weekly"]):
        return "sync"
    if any(word in lower for word in ["interview", "面试"]):
        return "interview"
    return "meeting"


__all__ = ["GoogleCalendarConnector", "sanitize_calendar_events"]
```

- [ ] **Step 6: Run provider tests**

Run:

```bash
cd backend && uv run pytest tests/test_dev_review_providers.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit provider normalization**

```bash
git add backend/app/config.py backend/app/mcp/github.py backend/app/mcp/google_calendar.py backend/tests/test_dev_review_providers.py
git commit -m "feat: normalize dev review providers"
```

## Task 4: DevReviewAgent Synthesis and Fallback

**Files:**
- Modify: `backend/app/core/prompts.py`
- Create: `backend/app/agents/dev_review_agent.py`
- Test: `backend/tests/test_dev_review_agent.py`

- [ ] **Step 1: Write failing agent tests**

Create `backend/tests/test_dev_review_agent.py`:

```python
from __future__ import annotations

import pytest

from app.agents.dev_review_agent import DevReviewAgent
from app.memory.schemas import ProviderContext


class FailingLLM:
    async def chat_json(self, *args, **kwargs):
        raise RuntimeError("llm unavailable")


@pytest.mark.asyncio
async def test_dev_review_agent_fallback_uses_provider_signals():
    agent = DevReviewAgent(FailingLLM())
    review = await agent.synthesize(
        window_days=7,
        contexts=[
            ProviderContext(
                source="github",
                status="success",
                window_days=7,
                signals={
                    "events": 8,
                    "repos": ["owner/weatherflow"],
                    "event_types": {"PullRequestEvent": 2},
                },
            ),
            ProviderContext(
                source="google_calendar",
                status="success",
                window_days=7,
                signals={
                    "meeting_count": 12,
                    "meeting_hours": 8.5,
                    "events": [{"title": "WeatherFlow architecture sync"}],
                },
            ),
        ],
    )

    assert review.dev_weather in {
        "Deep Work",
        "Shipping",
        "Collaboration Heavy",
        "Fragmented",
        "Blocked",
    }
    assert review.summary
    assert "owner/weatherflow" in review.main_work_threads[0]
    assert any("12" in item for item in review.meeting_load)
    assert review.source_coverage["github"] == "success"
    assert review.source_coverage["google_calendar"] == "success"
```

- [ ] **Step 2: Run failing agent tests**

Run:

```bash
cd backend && uv run pytest tests/test_dev_review_agent.py -v
```

Expected: FAIL because `DevReviewAgent` does not exist.

- [ ] **Step 3: Add the system prompt**

In `backend/app/core/prompts.py`, add:

```python
DEV_REVIEW_SYSTEM = """\
You are WeatherFlow's Dev Review Agent.

Your job: synthesize a development rhythm review from GitHub and Google Calendar
provider summaries. Describe the user's development rhythm, not their inner
mental or physical state.

Output STRICT JSON:
{
  "summary": "<one concise paragraph in Simplified Chinese>",
  "dev_weather": "Deep Work" | "Shipping" | "Collaboration Heavy" | "Fragmented" | "Blocked",
  "main_work_threads": ["<1-5 concise items>"],
  "shipping_progress": ["<evidence-backed progress items>"],
  "collaboration_load": ["<review / issue / collaboration load items>"],
  "meeting_load": ["<calendar load items, may cite event titles>"],
  "rhythm_risks": ["<evidence-backed risks only>"],
  "next_week_suggestion": "<one small suggestion in Simplified Chinese>",
  "source_coverage": {"github": "...", "google_calendar": "..."}
}

Constraints:
- Write user-facing text in Simplified Chinese.
- Keep English enum values exactly as specified.
- Do not infer mood, burnout, health, or psychological state.
- Use only evidence present in provider summaries.
- Give exactly one next-week suggestion.
"""
```

Add `DEV_REVIEW_SYSTEM` to `__all__`.

- [ ] **Step 4: Implement `DevReviewAgent`**

Create `backend/app/agents/dev_review_agent.py`:

```python
"""Dev Review Agent: fixed-purpose development rhythm synthesis."""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.core.prompts import DEV_REVIEW_SYSTEM
from app.memory.schemas import DevReviewCreate, ProviderContext


class DevReviewAgent(BaseAgent):
    async def synthesize(
        self,
        *,
        window_days: int,
        contexts: list[ProviderContext],
    ) -> DevReviewCreate:
        source_coverage = {ctx.source: ctx.status for ctx in contexts}
        user = {
            "window_days": window_days,
            "provider_contexts": [ctx.model_dump() for ctx in contexts],
        }
        try:
            data = await self.llm.chat_json(
                [
                    {"role": "system", "content": DEV_REVIEW_SYSTEM},
                    {"role": "user", "content": str(user)},
                ],
                temperature=0.3,
                max_tokens=900,
            )
            data["run_id"] = 0
            data["window_days"] = window_days
            data["source_coverage"] = {
                **source_coverage,
                **dict(data.get("source_coverage") or {}),
            }
            return DevReviewCreate(**data)
        except Exception:
            return _fallback_review(window_days=window_days, contexts=contexts)


def _fallback_review(*, window_days: int, contexts: list[ProviderContext]) -> DevReviewCreate:
    by_source = {ctx.source: ctx for ctx in contexts}
    github = by_source.get("github")
    calendar = by_source.get("google_calendar")
    source_coverage = {ctx.source: ctx.status for ctx in contexts}

    repos = list((github.signals.get("repos") if github else []) or [])
    events = int((github.signals.get("events") if github else 0) or 0)
    meeting_count = int((calendar.signals.get("meeting_count") if calendar else 0) or 0)
    meeting_hours = float((calendar.signals.get("meeting_hours") if calendar else 0) or 0)

    dev_weather = _weather_from(events=events, meeting_hours=meeting_hours, repos=len(repos))
    main_threads = repos[:5] or ["本窗口没有足够的 GitHub 工作线索"]
    meeting_titles = [
        str(e.get("title"))
        for e in ((calendar.signals.get("events") if calendar else []) or [])[:3]
        if e.get("title")
    ]

    return DevReviewCreate(
        run_id=0,
        window_days=window_days,
        summary=f"过去 {window_days} 天里，开发节奏主要由 {events} 条 GitHub 活动和 {meeting_count} 个日历事件构成。",
        dev_weather=dev_weather,
        main_work_threads=main_threads,
        shipping_progress=[f"GitHub 返回 {events} 条近期开发活动。"] if github else [],
        collaboration_load=_github_collaboration_items(github),
        meeting_load=[f"{meeting_count} 个会议/日历事件，约 {meeting_hours:g} 小时。"] + meeting_titles,
        rhythm_risks=_risk_items(events=events, meeting_count=meeting_count, meeting_hours=meeting_hours),
        next_week_suggestion="下周可以先保护一个连续的深度工作窗口，再打开新的协作线程。",
        source_coverage=source_coverage,
    )


def _weather_from(*, events: int, meeting_hours: float, repos: int) -> str:
    if events == 0 and meeting_hours >= 8:
        return "Blocked"
    if meeting_hours >= 10:
        return "Collaboration Heavy"
    if repos >= 4:
        return "Fragmented"
    if events >= 8:
        return "Shipping"
    return "Deep Work"


def _github_collaboration_items(github: ProviderContext | None) -> list[str]:
    if github is None:
        return []
    event_types: dict[str, Any] = dict(github.signals.get("event_types") or {})
    items: list[str] = []
    for name in ["PullRequestReviewEvent", "PullRequestEvent", "IssueCommentEvent", "IssuesEvent"]:
        count = int(event_types.get(name) or 0)
        if count:
            items.append(f"{name}: {count}")
    return items


def _risk_items(*, events: int, meeting_count: int, meeting_hours: float) -> list[str]:
    risks: list[str] = []
    if meeting_hours >= 10:
        risks.append("会议时间偏高，可能挤压连续开发窗口。")
    if meeting_count >= 15:
        risks.append("会议数量偏多，开发上下文可能被频繁切开。")
    if events == 0 and meeting_count > 0:
        risks.append("日历有活动但 GitHub 信号较少，本次复盘可能看不到实际开发推进。")
    return risks


__all__ = ["DevReviewAgent"]
```

- [ ] **Step 5: Run agent tests**

Run:

```bash
cd backend && uv run pytest tests/test_dev_review_agent.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit agent synthesis**

```bash
git add backend/app/core/prompts.py backend/app/agents/dev_review_agent.py backend/tests/test_dev_review_agent.py
git commit -m "feat: synthesize dev reviews"
```

## Task 5: API Orchestration

**Files:**
- Create: `backend/app/routers/dev_review.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_dev_review_api.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_dev_review_api.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def test_dev_review_fails_when_no_provider_configured(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    client = TestClient(create_app())

    with client:
        response = client.post("/api/dev-review/runs", json={"window_days": 7})

    assert response.status_code == 400
    assert "at least one provider" in response.text


def test_latest_returns_null_when_no_review_exists():
    client = TestClient(create_app())

    with client:
        response = client.get("/api/dev-review/runs/latest")

    assert response.status_code == 200
    assert response.json() is None
```

- [ ] **Step 2: Run failing API tests**

Run:

```bash
cd backend && uv run pytest tests/test_dev_review_api.py -v
```

Expected: FAIL because the router does not exist.

- [ ] **Step 3: Implement dev review router**

Create `backend/app/routers/dev_review.py`:

```python
"""Dev Review Agent Run endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.agents.dev_review_agent import DevReviewAgent
from app.config import get_settings
from app.core.agent_runs import AgentRunTracker
from app.core.llm import LLMClient
from app.mcp.github import GithubConnector, normalize_github_summary
from app.mcp.google_calendar import GoogleCalendarConnector
from app.memory import dev_review_repo
from app.memory.schemas import (
    AgentRunCreate,
    DevReviewCreate,
    DevReviewRecord,
    DevReviewRunRequest,
    ProviderContext,
)
from app.routers._deps import get_llm

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dev-review", tags=["dev-review"])


@router.post("/runs", response_model=DevReviewRecord)
async def run_dev_review(
    payload: DevReviewRunRequest,
    llm: LLMClient = Depends(get_llm),
) -> DevReviewRecord:
    settings = get_settings()
    run_id = dev_review_repo.create_run(
        AgentRunCreate(
            input={"window_days": payload.window_days, "providers": payload.providers}
        )
    )
    tracker = AgentRunTracker(run_id)
    contexts: list[ProviderContext] = []

    if "github" in payload.providers:
        if not settings.github_token:
            tracker.step("github", "skipped", "GITHUB_TOKEN is not configured.")
        else:
            try:
                summary = await GithubConnector(settings.github_token).fetch(days=payload.window_days)
                ctx = normalize_github_summary(summary, window_days=payload.window_days)
                contexts.append(ctx)
                tracker.step("github", ctx.status, "GitHub context collected.", ctx.coverage)
            except Exception as exc:
                logger.exception("GitHub dev review context failed")
                tracker.step("github", "failed", str(exc), {})

    if "google_calendar" in payload.providers:
        if not settings.google_calendar_access_token:
            tracker.step("google_calendar", "skipped", "GOOGLE_CALENDAR_ACCESS_TOKEN is not configured.")
        else:
            try:
                conn = GoogleCalendarConnector(
                    settings.google_calendar_access_token,
                    calendar_id=settings.google_calendar_calendar_id,
                    base_url=settings.google_calendar_base_url,
                )
                ctx = await conn.fetch(days=payload.window_days)
                contexts.append(ctx)
                tracker.step("google_calendar", ctx.status, "Google Calendar context collected.", ctx.coverage)
            except Exception as exc:
                logger.exception("Google Calendar dev review context failed")
                tracker.step("google_calendar", "failed", str(exc), {})

    if not contexts:
        tracker.fail("Configure at least one provider: GitHub or Google Calendar.")
        raise HTTPException(status_code=400, detail="Configure at least one provider before running dev review.")

    draft = await DevReviewAgent(llm).synthesize(window_days=payload.window_days, contexts=contexts)
    review_id = dev_review_repo.create_review(
        DevReviewCreate(**{**draft.model_dump(), "run_id": run_id})
    )
    tracker.finish()
    review = dev_review_repo.get_review(review_id)
    assert review is not None
    return review


@router.get("/runs/latest", response_model=DevReviewRecord | None)
async def latest_dev_review() -> DevReviewRecord | None:
    return dev_review_repo.latest_review()


@router.get("/runs/{run_id}", response_model=DevReviewRecord)
async def get_dev_review(run_id: int) -> DevReviewRecord:
    review = dev_review_repo.latest_review_for_run(run_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Dev review not found.")
    return review
```

- [ ] **Step 4: Include router**

In `backend/app/main.py`, update imports:

```python
from app.routers import checkin, dev_review, feedback, mcp, memory, reflection, sensors, state
```

Add after `app.include_router(checkin.router)`:

```python
    app.include_router(dev_review.router)
```

- [ ] **Step 5: Run API tests**

Run:

```bash
cd backend && uv run pytest tests/test_dev_review_api.py -v
```

Expected: PASS.

- [ ] **Step 6: Run focused backend suite**

Run:

```bash
cd backend && uv run pytest tests/test_dev_review_repo.py tests/test_agent_runs.py tests/test_dev_review_providers.py tests/test_dev_review_agent.py tests/test_dev_review_api.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit API orchestration**

```bash
git add backend/app/routers/dev_review.py backend/app/main.py backend/tests/test_dev_review_api.py
git commit -m "feat: expose dev review runs api"
```

## Task 6: CLI Command

**Files:**
- Create: `cli/weatherflow_cli/dev_review.py`
- Modify: `cli/weatherflow_cli/__main__.py`
- Test: `backend tests are enough for API; manually verify CLI against a running backend`

- [ ] **Step 1: Implement CLI command**

Create `cli/weatherflow_cli/dev_review.py`:

```python
"""Dev Review Agent Run CLI."""

from __future__ import annotations

import typer

from weatherflow_cli import api


def run(
    days: int = typer.Option(7, "--days", min=1, max=31, help="Review window in days."),
    latest: bool = typer.Option(False, "--latest", help="Show latest saved review instead of running a new one."),
) -> None:
    try:
        if latest:
            data = api.get("/api/dev-review/runs/latest")
            if data is None:
                typer.echo("No dev review has been saved yet.")
                return
        else:
            data = api.post("/api/dev-review/runs", json={"window_days": days})
    except Exception as exc:
        typer.echo(f"Dev review failed: {exc}")
        raise typer.Exit(code=1) from exc

    _print_review(data)


def _print_review(data: dict) -> None:
    typer.echo(f"Dev Weather: {data.get('dev_weather', '-')}")
    typer.echo("")
    typer.echo("Summary")
    typer.echo(data.get("summary", "-"))
    typer.echo("")
    _section("Main Work Threads", data.get("main_work_threads") or [])
    _section("Shipping Progress", data.get("shipping_progress") or [])
    _section("Collaboration Load", data.get("collaboration_load") or [])
    _section("Meeting Load", data.get("meeting_load") or [])
    _section("Rhythm Risks", data.get("rhythm_risks") or [])
    typer.echo("Next Week Suggestion")
    typer.echo(data.get("next_week_suggestion", "-"))
    typer.echo("")
    typer.echo("Source Coverage")
    coverage = data.get("source_coverage") or {}
    for name, status in coverage.items():
        typer.echo(f"- {name}: {status}")
    run = data.get("run") or {}
    if run.get("status") == "partial":
        typer.echo("")
        typer.echo("Trace")
        for step in run.get("steps") or []:
            typer.echo(f"- {step.get('name')}: {step.get('status')} — {step.get('summary')}")


def _section(title: str, items: list[str]) -> None:
    typer.echo(title)
    if not items:
        typer.echo("-")
    for item in items:
        typer.echo(f"- {item}")
    typer.echo("")
```

- [ ] **Step 2: Register CLI command**

In `cli/weatherflow_cli/__main__.py`, add import:

```python
from weatherflow_cli import dev_review as dev_review_cmd
```

Register before `patterns`:

```python
app.command(name="dev-review", help="Run or show the Dev Review Agent.")(dev_review_cmd.run)
```

- [ ] **Step 3: Manually verify CLI help**

Run:

```bash
uv run wf dev-review --help
```

Expected: help includes `--days` and `--latest`.

- [ ] **Step 4: Commit CLI command**

```bash
git add cli/weatherflow_cli/dev_review.py cli/weatherflow_cli/__main__.py
git commit -m "feat: add dev review cli"
```

## Task 7: Dashboard Panel

**Files:**
- Modify: `frontend/lib/api.ts`
- Create: `frontend/components/DevReviewPanel.tsx`
- Modify: `frontend/app/page.tsx`

- [ ] **Step 1: Add frontend types and API helpers**

In `frontend/lib/api.ts`, add:

```ts
export type DevWeather =
  | "Deep Work"
  | "Shipping"
  | "Collaboration Heavy"
  | "Fragmented"
  | "Blocked";

export interface AgentRunStep {
  name: string;
  status: "success" | "partial" | "failed" | "skipped";
  summary: string;
  metadata: Record<string, unknown>;
}

export interface AgentRunRecord {
  id: number;
  run_type: "dev_review";
  status: "running" | "success" | "partial" | "failed";
  started_at: string;
  finished_at?: string | null;
  input: Record<string, unknown>;
  steps: AgentRunStep[];
  error?: string | null;
}

export interface DevReview {
  id: number;
  run_id: number;
  window_days: number;
  summary: string;
  dev_weather: DevWeather;
  main_work_threads: string[];
  shipping_progress: string[];
  collaboration_load: string[];
  meeting_load: string[];
  rhythm_risks: string[];
  next_week_suggestion: string;
  source_coverage: Record<string, unknown>;
  created_at: string;
  run: AgentRunRecord;
}
```

Add helpers to `api`:

```ts
  latestDevReview: () => request<DevReview | null>("/api/dev-review/runs/latest"),
  runDevReview: (windowDays = 7) =>
    request<DevReview>("/api/dev-review/runs", {
      method: "POST",
      body: JSON.stringify({ window_days: windowDays })
    }),
```

- [ ] **Step 2: Create panel component**

Create `frontend/components/DevReviewPanel.tsx`:

```tsx
"use client";

import { useState } from "react";
import { api, type DevReview } from "@/lib/api";

export function DevReviewPanel({ initial }: { initial: DevReview | null }) {
  const [review, setReview] = useState<DevReview | null>(initial);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runReview() {
    setRunning(true);
    setError(null);
    try {
      const next = await api.runDevReview(7);
      setReview(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dev review failed.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-widest muted">Dev Review</div>
          <h2 className="mt-2 font-serif text-2xl">{review?.dev_weather || "Not run yet"}</h2>
        </div>
        <button
          className="btn"
          type="button"
          onClick={runReview}
          disabled={running}
        >
          {running ? "Running..." : "Run"}
        </button>
      </div>

      {error ? <p className="mt-3 text-sm text-red-600">{error}</p> : null}

      <p className="mt-4 leading-relaxed">
        {review?.summary || "Run a dev review to connect GitHub and Calendar context into one development rhythm snapshot."}
      </p>

      {review ? (
        <>
          <div className="mt-5">
            <div className="text-xs uppercase tracking-widest muted">Next Week</div>
            <p className="mt-2 leading-relaxed">{review.next_week_suggestion}</p>
          </div>
          <div className="mt-5 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <MiniList title="Work Threads" items={review.main_work_threads} />
            <MiniList title="Rhythm Risks" items={review.rhythm_risks} />
          </div>
          <details className="mt-5 text-sm">
            <summary className="cursor-pointer muted">Source coverage</summary>
            <div className="mt-2 space-y-1">
              {Object.entries(review.source_coverage).map(([name, status]) => (
                <div key={name} className="flex justify-between gap-4">
                  <span>{name}</span>
                  <span>{String(status)}</span>
                </div>
              ))}
              {review.run.steps.map((step) => (
                <div key={`${step.name}-${step.status}`} className="muted">
                  {step.name}: {step.status} — {step.summary}
                </div>
              ))}
            </div>
          </details>
        </>
      ) : null}
    </div>
  );
}

function MiniList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-widest muted">{title}</div>
      <ul className="mt-2 space-y-1">
        {(items.length ? items : ["-"]).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 3: Render panel on dashboard**

In `frontend/app/page.tsx`, import:

```tsx
import { DevReviewPanel } from "@/components/DevReviewPanel";
```

Add `DevReview` type import:

```tsx
  DevReview,
```

Add fetch:

```tsx
      fetchOk<DevReview>("/api/dev-review/runs/latest")
```

Update destructuring:

```tsx
  const [state, reflections, profile, hypotheses, devReview] =
```

Render after the state cards:

```tsx
      <section>
        <DevReviewPanel initial={devReview} />
      </section>
```

- [ ] **Step 4: Run frontend checks**

Run:

```bash
cd frontend && npm run lint
cd frontend && npm run build
```

Expected: both pass.

- [ ] **Step 5: Commit dashboard panel**

```bash
git add frontend/lib/api.ts frontend/components/DevReviewPanel.tsx frontend/app/page.tsx
git commit -m "feat: add dev review dashboard panel"
```

## Task 8: Documentation and Final Verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: Document configuration**

In `.env.example`, add:

```text
# Dev Review providers
GITHUB_TOKEN=
GOOGLE_CALENDAR_ACCESS_TOKEN=
GOOGLE_CALENDAR_CALENDAR_ID=primary
GOOGLE_CALENDAR_BASE_URL=https://www.googleapis.com/calendar/v3
```

In `README.md`, add under Quick Start CLI examples:

```bash
uv run wf dev-review --days 7      # development rhythm review from GitHub + Calendar
uv run wf dev-review --latest      # latest saved dev review
```

Add a short note:

```markdown
### Dev Review Agent

The Dev Review Agent is a manually triggered agent run. It uses configured
GitHub and Google Calendar providers to generate a structured development
rhythm review, stores the user-facing review, and keeps a lightweight execution
trace for provider coverage and failures. Calendar storage keeps event titles,
start times, durations, calendar names, and derived categories; it does not
store descriptions, attendee emails, meeting links, locations, or attachments.
```

- [ ] **Step 2: Run focused backend tests**

Run:

```bash
cd backend && uv run pytest tests/test_dev_review_repo.py tests/test_agent_runs.py tests/test_dev_review_providers.py tests/test_dev_review_agent.py tests/test_dev_review_api.py -v
```

Expected: PASS.

- [ ] **Step 3: Run full project check**

Run:

```bash
make check
```

Expected: PASS.

- [ ] **Step 4: Manually verify API failure state**

With no provider tokens configured, run:

```bash
curl -s -X POST http://127.0.0.1:8765/api/dev-review/runs \
  -H 'Content-Type: application/json' \
  -d '{"window_days":7}'
```

Expected: HTTP 400 response saying to configure at least one provider.

- [ ] **Step 5: Commit docs**

```bash
git add README.md .env.example
git commit -m "docs: document dev review agent"
```

## Self-Review Notes

- Spec coverage: persistence, run lifecycle, provider normalization, Google Calendar title-level storage, LLM fallback, API, CLI, dashboard, docs, and tests are covered.
- Scope check: first version remains GitHub + Google Calendar only. Feishu and WeChat are deferred.
- Sensor policy: no task uses local git/workspace/notes sensors for Dev Review.
- Privacy policy: Calendar tests and docs explicitly preserve titles while dropping descriptions, attendees, links, locations, and attachments.
- Type consistency: `dev_weather`, `rhythm_risks`, `source_coverage`, `agent_runs`, and `dev_reviews` names match the approved spec.
