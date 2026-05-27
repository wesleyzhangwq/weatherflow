# Chat Assignment Agent Implementation Plan

> Superseded by [ReAct Hypothesis Orchestration Implementation Plan](2026-05-22-react-hypothesis-orchestration.md). Keep this file only as historical context for the earlier chat-assignment direction.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a chat-first assignment layer where users can ask WeatherFlow to reason over their current rhythm context and propose safe Calendar/GitHub actions for confirmation.

**Architecture:** Keep the existing check-in pipeline as the durable state signal. Add a new `AssignmentAgent` and `/api/assignments` router that load profile, check-ins, latest state, latest Dev Review, available MCP tool metadata, and existing action proposal rules. The agent returns a conversational answer plus zero or more `ActionProposal` objects; side-effecting tools remain confirmation-gated through the existing `/api/actions/{proposal_id}/execute` endpoint.

**Tech Stack:** FastAPI, Pydantic models in `backend/app/memory/schemas.py`, SQLite repositories in `backend/app/memory`, MCP client infrastructure in `backend/app/mcp_client`, existing `ActionProposal`, Next.js app router, TypeScript fetch helpers.

---

## File Structure

- Create `backend/app/agents/assignment_agent.py`: LLM-backed assignment/chat agent; classifies intent, builds tool-safe proposals, and produces user-facing replies.
- Create `backend/app/memory/assignment_repo.py`: SQLite persistence for assignment turns and linked proposal ids.
- Modify `backend/app/memory/store.py`: add `assignment_turns` table migration.
- Modify `backend/app/memory/schemas.py`: add request/response/record models for assignment chat.
- Modify `backend/app/routers/actions.py`: add proposal listing so chat UI can render pending proposals.
- Create `backend/app/routers/assignments.py`: API endpoint for chat assignments.
- Modify `backend/app/main.py`: import `assignments` and call `app.include_router(assignments.router)`.
- Modify `backend/app/core/prompts.py`: add `ASSIGNMENT_SYSTEM`.
- Modify `backend/app/agents/__init__.py`: export `AssignmentAgent`.
- Modify `frontend/lib/api.ts`: add assignment and proposal API helpers.
- Create `frontend/components/AssignmentChat.tsx`: chat panel with messages and proposal cards.
- Modify `frontend/app/page.tsx`: add assignment chat as a primary dashboard workspace.
- Add tests:
  - `backend/tests/test_assignment_agent.py`
  - `backend/tests/test_assignment_api.py`
  - `backend/tests/test_actions_api.py`

## Product Contract

The first implementation supports these assignment intents:

1. `answer`: answer using WeatherFlow context without proposing tool actions.
2. `plan`: produce 1-3 rhythm options without proposing tool actions.
3. `calendar_focus_block`: propose `calendar.create_focus_block`.
4. `calendar_event`: propose `calendar.create_event`.
5. `github_issue`: propose `github.create_issue`.

The agent must not execute tools directly. It may only return `ActionProposal` objects. Users confirm execution through `/api/actions/{proposal_id}/execute`.

## Task 1: Persist Assignment Turns

**Files:**
- Modify: `backend/app/memory/schemas.py`
- Modify: `backend/app/memory/store.py`
- Create: `backend/app/memory/assignment_repo.py`
- Test: `backend/tests/test_assignment_repo.py`

- [ ] **Step 1: Write failing repository tests**

Create `backend/tests/test_assignment_repo.py`:

```python
from __future__ import annotations

from app.memory import assignment_repo
from app.memory.schemas import AssignmentTurnCreate


def test_assignment_repo_creates_and_lists_turns() -> None:
    created = assignment_repo.create_turn(
        AssignmentTurnCreate(
            session_id="default",
            user_message="Help me plan tomorrow.",
            assistant_message="Start with one protected focus block.",
            intent="plan",
            proposal_ids=[],
            context_snapshot={"weather_label": "Momentum"},
        )
    )

    assert created.id == 1
    assert created.session_id == "default"
    assert created.intent == "plan"
    assert created.context_snapshot["weather_label"] == "Momentum"

    turns = assignment_repo.recent(session_id="default", limit=10)
    assert [turn.id for turn in turns] == [1]
    assert turns[0].assistant_message == "Start with one protected focus block."


def test_assignment_repo_filters_by_session() -> None:
    assignment_repo.create_turn(
        AssignmentTurnCreate(
            session_id="alpha",
            user_message="A",
            assistant_message="A reply",
            intent="answer",
            proposal_ids=[],
            context_snapshot={},
        )
    )
    assignment_repo.create_turn(
        AssignmentTurnCreate(
            session_id="beta",
            user_message="B",
            assistant_message="B reply",
            intent="answer",
            proposal_ids=[],
            context_snapshot={},
        )
    )

    assert [turn.session_id for turn in assignment_repo.recent(session_id="alpha")] == ["alpha"]
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --project backend pytest backend/tests/test_assignment_repo.py -q
```

Expected: FAIL with `ImportError: cannot import name 'assignment_repo'` or missing `AssignmentTurnCreate`.

- [ ] **Step 3: Add assignment schemas**

In `backend/app/memory/schemas.py`, add:

```python
AssignmentIntent = Literal[
    "answer",
    "plan",
    "calendar_focus_block",
    "calendar_event",
    "github_issue",
]


class AssignmentTurnCreate(BaseModel):
    session_id: str = "default"
    user_message: str
    assistant_message: str
    intent: AssignmentIntent = "answer"
    proposal_ids: List[str] = Field(default_factory=list)
    context_snapshot: Dict[str, Any] = Field(default_factory=dict)


class AssignmentTurnRecord(AssignmentTurnCreate):
    id: int
    created_at: str


class AssignmentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str = "default"


class AssignmentChatResponse(BaseModel):
    turn: AssignmentTurnRecord
    proposals: List[ActionProposal] = Field(default_factory=list)
```

Add the new names to `__all__`.

- [ ] **Step 4: Add database table**

In `backend/app/memory/store.py`, inside the initialization/migration function that creates existing tables, add:

```python
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS assignment_turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL DEFAULT 'default',
        user_message TEXT NOT NULL,
        assistant_message TEXT NOT NULL,
        intent TEXT NOT NULL DEFAULT 'answer',
        proposal_ids_json TEXT NOT NULL DEFAULT '[]',
        context_snapshot_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """
)
```

- [ ] **Step 5: Implement repository**

Create `backend/app/memory/assignment_repo.py`:

```python
from __future__ import annotations

import json

from app.memory.schemas import AssignmentTurnCreate, AssignmentTurnRecord
from app.memory.store import connect


def _row_to_record(row) -> AssignmentTurnRecord:
    return AssignmentTurnRecord(
        id=int(row["id"]),
        session_id=str(row["session_id"]),
        user_message=str(row["user_message"]),
        assistant_message=str(row["assistant_message"]),
        intent=row["intent"],
        proposal_ids=list(json.loads(row["proposal_ids_json"] or "[]")),
        context_snapshot=dict(json.loads(row["context_snapshot_json"] or "{}")),
        created_at=str(row["created_at"]),
    )


def create_turn(turn: AssignmentTurnCreate) -> AssignmentTurnRecord:
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO assignment_turns (
                session_id,
                user_message,
                assistant_message,
                intent,
                proposal_ids_json,
                context_snapshot_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                turn.session_id,
                turn.user_message,
                turn.assistant_message,
                turn.intent,
                json.dumps(turn.proposal_ids),
                json.dumps(turn.context_snapshot),
            ),
        )
        row = conn.execute(
            "SELECT * FROM assignment_turns WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _row_to_record(row)


def recent(*, session_id: str = "default", limit: int = 20) -> list[AssignmentTurnRecord]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM assignment_turns
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    return [_row_to_record(row) for row in reversed(rows)]
```

- [ ] **Step 6: Run repository tests**

Run:

```bash
uv run --project backend pytest backend/tests/test_assignment_repo.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/memory/schemas.py backend/app/memory/store.py backend/app/memory/assignment_repo.py backend/tests/test_assignment_repo.py
git commit -m "feat: persist assignment chat turns"
```

## Task 2: Build Assignment Context and Agent

**Files:**
- Create: `backend/app/agents/assignment_agent.py`
- Modify: `backend/app/core/prompts.py`
- Modify: `backend/app/agents/__init__.py`
- Test: `backend/tests/test_assignment_agent.py`

- [ ] **Step 1: Write failing agent tests**

Create `backend/tests/test_assignment_agent.py`:

```python
from __future__ import annotations

import json
from typing import Any

from app.agents.assignment_agent import AssignmentAgent
from app.memory.schemas import ActionProposal


class FakeAssignmentLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[list[dict[str, str]]] = []

    async def chat_json(self, messages, **kwargs):
        self.calls.append(messages)
        return self.payload


async def test_assignment_agent_returns_answer_without_proposals() -> None:
    agent = AssignmentAgent(
        FakeAssignmentLLM(
            {
                "intent": "answer",
                "assistant_message": "今天先保护一个小闭环。",
                "proposals": [],
            }
        )
    )

    result = await agent.respond(
        message="我今天有点乱，帮我判断一下。",
        context={"latest_state": {"weather_label": "Overload"}},
        available_tools=[],
    )

    assert result.intent == "answer"
    assert result.assistant_message == "今天先保护一个小闭环。"
    assert result.proposals == []


async def test_assignment_agent_sanitizes_focus_block_proposal() -> None:
    agent = AssignmentAgent(
        FakeAssignmentLLM(
            {
                "intent": "calendar_focus_block",
                "assistant_message": "我建议先挡一段 90 分钟专注时间。",
                "proposals": [
                    {
                        "kind": "focus_block",
                        "title": "Deep Work: WeatherFlow Phase 3",
                        "rationale": "用户要求安排专注时间。",
                        "tool_name": "calendar.create_focus_block",
                        "tool_arguments": {
                            "title": "Deep Work: WeatherFlow Phase 3",
                            "duration_minutes": 90,
                            "preferred_time": "morning",
                        },
                    }
                ],
            }
        )
    )

    result = await agent.respond(
        message="帮我明天安排一个 deep work block。",
        context={"latest_state": {"weather_label": "Momentum"}},
        available_tools=["calendar.create_focus_block"],
    )

    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert isinstance(proposal, ActionProposal)
    assert proposal.requires_confirmation is True
    assert proposal.tool_name == "calendar.create_focus_block"
    assert proposal.tool_arguments["duration_minutes"] == 90


async def test_assignment_agent_drops_unavailable_tool_proposals() -> None:
    agent = AssignmentAgent(
        FakeAssignmentLLM(
            {
                "intent": "github_issue",
                "assistant_message": "可以建一个 issue，但当前工具不可用。",
                "proposals": [
                    {
                        "kind": "github_issue",
                        "title": "Track blocker",
                        "rationale": "用户提到 blocker。",
                        "tool_name": "github.create_issue",
                        "tool_arguments": {"title": "Track blocker", "body": "Created by WF."},
                    }
                ],
            }
        )
    )

    result = await agent.respond(
        message="把 blocker 建成 issue。",
        context={},
        available_tools=[],
    )

    assert result.intent == "github_issue"
    assert result.proposals == []
    assert "当前工具不可用" in result.assistant_message
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --project backend pytest backend/tests/test_assignment_agent.py -q
```

Expected: FAIL because `app.agents.assignment_agent` does not exist.

- [ ] **Step 3: Add assignment prompt**

In `backend/app/core/prompts.py`, add:

```python
ASSIGNMENT_SYSTEM = """
You are WeatherFlow's assignment agent.
You help the user choose and shape the next useful move from their current developer rhythm context.

Return strict JSON:
{
  "intent": "answer|plan|calendar_focus_block|calendar_event|github_issue",
  "assistant_message": "short user-facing reply in Chinese",
  "proposals": [
    {
      "kind": "focus_block|calendar_event|github_issue",
      "title": "short title",
      "rationale": "why this action fits",
      "tool_name": "calendar.create_focus_block|calendar.create_event|github.create_issue",
      "tool_arguments": {}
    }
  ]
}

Rules:
- Never claim you executed a tool.
- Only propose tools listed in available_tools.
- Use proposals for side effects; otherwise answer conversationally.
- Keep the tone gentle and practical.
- Prefer one proposal unless the user explicitly asks for options.
"""
```

- [ ] **Step 4: Implement AssignmentAgent**

Create `backend/app/agents/assignment_agent.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.agents.base import BaseAgent
from app.core.llm import chat_json
from app.core.model_router import model_for
from app.core.prompts import ASSIGNMENT_SYSTEM
from app.memory.schemas import ActionProposal, AssignmentIntent


_ALLOWED_TOOL_BY_KIND = {
    "focus_block": "calendar.create_focus_block",
    "calendar_event": "calendar.create_event",
    "github_issue": "github.create_issue",
}


@dataclass
class AssignmentAgentResult:
    intent: AssignmentIntent
    assistant_message: str
    proposals: list[ActionProposal]


class AssignmentAgent(BaseAgent):
    async def respond(
        self,
        *,
        message: str,
        context: dict[str, Any],
        available_tools: list[str],
    ) -> AssignmentAgentResult:
        raw = await self._chat_json(
            [
                {"role": "system", "content": ASSIGNMENT_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": message,
                            "context": context,
                            "available_tools": available_tools,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                },
            ],
            temperature=0.35,
            max_tokens=900,
        )
        intent = raw.get("intent") if raw.get("intent") in AssignmentIntent.__args__ else "answer"
        assistant_message = str(raw.get("assistant_message") or "").strip()
        if not assistant_message:
            assistant_message = "我先给你一个小选择：把下一步收窄成一个可确认的动作。"
        proposals = _sanitize_proposals(raw.get("proposals") or [], available_tools)
        return AssignmentAgentResult(
            intent=intent,
            assistant_message=assistant_message,
            proposals=proposals,
        )

    async def _chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        llm_chat_json = getattr(self.llm, "chat_json", None)
        if callable(llm_chat_json):
            return await llm_chat_json(messages, temperature=temperature, max_tokens=max_tokens)
        return await chat_json(
            self.llm,
            messages,
            model=model_for("planning"),
            temperature=temperature,
            max_tokens=max_tokens,
        )


def _sanitize_proposals(raw_items: list[dict[str, Any]], available_tools: list[str]) -> list[ActionProposal]:
    proposals: list[ActionProposal] = []
    available = set(available_tools)
    for raw in raw_items[:3]:
        kind = str(raw.get("kind") or "")
        tool_name = str(raw.get("tool_name") or "")
        if _ALLOWED_TOOL_BY_KIND.get(kind) != tool_name:
            continue
        if tool_name not in available:
            continue
        arguments = dict(raw.get("tool_arguments") or {})
        title = str(raw.get("title") or arguments.get("title") or "WeatherFlow action").strip()
        rationale = str(raw.get("rationale") or "Suggested from the current WeatherFlow context.").strip()
        proposals.append(
            ActionProposal(
                kind=kind,
                title=title[:120],
                rationale=rationale[:240],
                tool_name=tool_name,
                tool_arguments=arguments,
                requires_confirmation=True,
            )
        )
    return proposals
```

- [ ] **Step 5: Export agent**

In `backend/app/agents/__init__.py`, import and add `AssignmentAgent` to `__all__`.

- [ ] **Step 6: Run agent tests**

Run:

```bash
uv run --project backend pytest backend/tests/test_assignment_agent.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agents/assignment_agent.py backend/app/core/prompts.py backend/app/agents/__init__.py backend/tests/test_assignment_agent.py
git commit -m "feat: add assignment agent"
```

## Task 3: Add Assignment API

**Files:**
- Create: `backend/app/routers/assignments.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/routers/actions.py`
- Test: `backend/tests/test_assignment_api.py`
- Test: `backend/tests/test_actions_api.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_assignment_api.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from app.agents.assignment_agent import AssignmentAgentResult
from app.config import get_settings
from app.main import create_app
from app.memory import checkin_repo, state_repo
from app.memory.schemas import ActionProposal, UserStateOut


def _client() -> TestClient:
    app = create_app()
    app.state.llm = object()
    return TestClient(app)


def test_assignment_chat_persists_turn_and_proposals(monkeypatch) -> None:
    checkin_repo.add(
        {
            "status": "clear",
            "did_today": "finished the MCP path",
            "stuck_on": "",
            "anxiety": "",
            "raw": "Need a focus block tomorrow.",
            "session_id": "default",
        }
    )
    state_repo.add(
        UserStateOut(
            focus=70,
            stress=35,
            burnout=20,
            momentum=75,
            confidence=70,
            motivation=70,
            weather_label="Momentum",
        )
    )
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "calendar-token")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    async def fake_respond(self, *, message, context, available_tools):
        assert "calendar.create_focus_block" in available_tools
        assert context["latest_state"]["weather_label"] == "Momentum"
        return AssignmentAgentResult(
            intent="calendar_focus_block",
            assistant_message="可以先挡一个 90 分钟专注块。",
            proposals=[
                ActionProposal(
                    kind="focus_block",
                    title="Deep Work: MCP cleanup",
                    rationale="Protect the current momentum.",
                    tool_name="calendar.create_focus_block",
                    tool_arguments={
                        "title": "Deep Work: MCP cleanup",
                        "duration_minutes": 90,
                        "preferred_time": "morning",
                    },
                )
            ],
        )

    monkeypatch.setattr("app.routers.assignments.AssignmentAgent.respond", fake_respond)

    client = _client()
    response = client.post(
        "/api/assignments/chat",
        json={"message": "帮我明天安排 deep work", "session_id": "default"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["turn"]["assistant_message"] == "可以先挡一个 90 分钟专注块。"
    assert body["turn"]["proposal_ids"] == [body["proposals"][0]["id"]]
    assert body["proposals"][0]["tool_name"] == "calendar.create_focus_block"
```

Append to `backend/tests/test_actions_api.py`:

```python
def test_list_proposals_returns_pending_items() -> None:
    created = _create_proposal(title="Deep Work: MCP cleanup")

    response = client.get("/api/actions/proposals")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [created["id"]]
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --project backend pytest backend/tests/test_assignment_api.py backend/tests/test_actions_api.py::test_list_proposals_returns_pending_items -q
```

Expected: FAIL because `/api/assignments/chat` and `GET /api/actions/proposals` do not exist.

- [ ] **Step 3: Add proposal listing**

In `backend/app/routers/actions.py`, add before `GET /proposals/{proposal_id}`:

```python
@router.get("/proposals", response_model=list[ActionProposal])
def list_proposals() -> list[ActionProposal]:
    return list(_PROPOSALS.values())
```

- [ ] **Step 4: Implement assignment router**

Create `backend/app/routers/assignments.py`:

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.agents.assignment_agent import AssignmentAgent
from app.config import get_settings
from app.memory import assignment_repo, checkin_repo, dev_review_repo, profile_md, state_repo
from app.memory.schemas import AssignmentChatRequest, AssignmentChatResponse, AssignmentTurnCreate
from app.routers._deps import get_llm
from app.routers.actions import create_proposal


router = APIRouter(prefix="/api/assignments", tags=["assignments"])


@router.post("/chat", response_model=AssignmentChatResponse)
async def chat_assignment(
    payload: AssignmentChatRequest,
    llm=Depends(get_llm),
) -> AssignmentChatResponse:
    context = _assignment_context(session_id=payload.session_id)
    available_tools = _available_assignment_tools()
    result = await AssignmentAgent(llm).respond(
        message=payload.message,
        context=context,
        available_tools=available_tools,
    )
    proposals = [create_proposal(proposal) for proposal in result.proposals]
    turn = assignment_repo.create_turn(
        AssignmentTurnCreate(
            session_id=payload.session_id,
            user_message=payload.message,
            assistant_message=result.assistant_message,
            intent=result.intent,
            proposal_ids=[proposal.id for proposal in proposals],
            context_snapshot=context,
        )
    )
    return AssignmentChatResponse(turn=turn, proposals=proposals)


def _assignment_context(*, session_id: str) -> dict[str, Any]:
    latest_state = state_repo.latest()
    latest_dev_review = dev_review_repo.latest_review()
    return {
        "session_id": session_id,
        "latest_checkin": (
            checkin_repo.latest().model_dump()
            if checkin_repo.latest()
            else None
        ),
        "recent_checkins": [item.model_dump() for item in checkin_repo.recent(limit=7)],
        "latest_state": latest_state.model_dump() if latest_state else None,
        "profile": profile_md.read_profile(max_chars=2500),
        "latest_dev_review": (
            {
                "dev_weather": latest_dev_review.dev_weather,
                "summary": latest_dev_review.summary,
                "rhythm_risks": latest_dev_review.rhythm_risks,
                "next_week_suggestion": latest_dev_review.next_week_suggestion,
            }
            if latest_dev_review
            else None
        ),
    }


def _available_assignment_tools() -> list[str]:
    settings = get_settings()
    tools: list[str] = []
    if settings.github_token.strip():
        tools.append("github.create_issue")
    if settings.google_calendar_access_token.strip() or settings.google_calendar_token_file.strip():
        tools.extend(["calendar.create_focus_block", "calendar.create_event"])
    return tools
```

- [ ] **Step 5: Register router**

In `backend/app/main.py`, update the router import:

```python
from app.routers import actions, assignments, checkin, dev_review, feedback, mcp, memory, reflection, state
```

Then include the router after actions:

```python
app.include_router(actions.router)
app.include_router(assignments.router)
app.include_router(checkin.router)
```

Leave `backend/app/routers/__init__.py` unchanged because it does not currently export router modules.

- [ ] **Step 6: Run API tests**

Run:

```bash
uv run --project backend pytest backend/tests/test_assignment_api.py backend/tests/test_actions_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/assignments.py backend/app/main.py backend/app/routers/actions.py backend/tests/test_assignment_api.py backend/tests/test_actions_api.py
git commit -m "feat: add assignment chat api"
```

## Task 4: Add Assignment UI

**Files:**
- Modify: `frontend/lib/api.ts`
- Create: `frontend/components/AssignmentChat.tsx`
- Modify: `frontend/app/page.tsx`

- [ ] **Step 1: Add API helpers**

In `frontend/lib/api.ts`, add these exported types and functions:

```typescript
export type ActionProposal = {
  id: string
  kind: 'calendar_event' | 'focus_block' | 'github_issue' | 'github_file_update'
  title: string
  rationale: string
  tool_name: string
  tool_arguments: Record<string, unknown>
  requires_confirmation: boolean
}

export type AssignmentTurn = {
  id: number
  session_id: string
  user_message: string
  assistant_message: string
  intent: string
  proposal_ids: string[]
  context_snapshot: Record<string, unknown>
  created_at: string
}

export type AssignmentChatResponse = {
  turn: AssignmentTurn
  proposals: ActionProposal[]
}

export async function sendAssignmentChat(message: string): Promise<AssignmentChatResponse> {
  return apiFetch<AssignmentChatResponse>('/api/assignments/chat', {
    method: 'POST',
    body: JSON.stringify({ message, session_id: 'default' }),
  })
}

export async function executeProposal(proposalId: string): Promise<{ proposal_id: string; tool_name: string; result: Record<string, unknown> }> {
  return apiFetch(`/api/actions/${proposalId}/execute`, {
    method: 'POST',
    body: JSON.stringify({ confirmed: true }),
  })
}
```

Use the existing `apiFetch` helper name if it differs; keep the same fetch wrapper style already present in `frontend/lib/api.ts`.

- [ ] **Step 2: Create chat component**

Create `frontend/components/AssignmentChat.tsx`:

```tsx
'use client'

import { FormEvent, useState } from 'react'
import { ActionProposal, executeProposal, sendAssignmentChat } from '@/lib/api'

type Message = {
  role: 'user' | 'assistant'
  content: string
  proposals?: ActionProposal[]
}

export default function AssignmentChat() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [executed, setExecuted] = useState<Record<string, string>>({})

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const message = input.trim()
    if (!message) return
    setInput('')
    setError(null)
    setIsLoading(true)
    setMessages((current) => [...current, { role: 'user', content: message }])
    try {
      const response = await sendAssignmentChat(message)
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: response.turn.assistant_message,
          proposals: response.proposals,
        },
      ])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Assignment failed')
    } finally {
      setIsLoading(false)
    }
  }

  async function confirmProposal(proposal: ActionProposal) {
    setError(null)
    try {
      await executeProposal(proposal.id)
      setExecuted((current) => ({ ...current, [proposal.id]: 'Executed' }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Execution failed')
    }
  }

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Assignment Chat</h2>
        <p className="text-sm text-zinc-500">
          Ask WeatherFlow to reason, plan, or prepare Calendar/GitHub actions for confirmation.
        </p>
      </div>

      <div className="space-y-3 rounded-lg border border-zinc-200 p-4">
        {messages.length === 0 ? (
          <p className="text-sm text-zinc-500">Try: “帮我把明天上午留给 WeatherFlow Phase 3。”</p>
        ) : null}
        {messages.map((message, index) => (
          <div key={index} className={message.role === 'user' ? 'text-right' : 'text-left'}>
            <div className="inline-block max-w-[85%] rounded-md bg-zinc-100 px-3 py-2 text-sm">
              {message.content}
            </div>
            {message.proposals?.map((proposal) => (
              <div key={proposal.id} className="mt-2 rounded-md border border-zinc-200 p-3 text-left">
                <div className="font-medium">{proposal.title}</div>
                <div className="mt-1 text-sm text-zinc-500">{proposal.rationale}</div>
                <button
                  type="button"
                  className="mt-3 rounded-md bg-zinc-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
                  onClick={() => confirmProposal(proposal)}
                  disabled={Boolean(executed[proposal.id])}
                >
                  {executed[proposal.id] ?? 'Confirm action'}
                </button>
              </div>
            ))}
          </div>
        ))}
      </div>

      <form onSubmit={onSubmit} className="flex gap-2">
        <input
          className="min-w-0 flex-1 rounded-md border border-zinc-300 px-3 py-2 text-sm"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Give WeatherFlow an assignment..."
        />
        <button
          type="submit"
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm text-white disabled:opacity-50"
          disabled={isLoading}
        >
          {isLoading ? 'Thinking' : 'Send'}
        </button>
      </form>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </section>
  )
}
```

- [ ] **Step 3: Mount on dashboard**

In `frontend/app/page.tsx`, import `AssignmentChat` and place it above or beside the existing Dev Review panel:

```tsx
import AssignmentChat from '@/components/AssignmentChat'

// inside the main dashboard JSX
<AssignmentChat />
```

Keep existing dashboard cards intact.

- [ ] **Step 4: Run frontend lint/build**

Run:

```bash
cd frontend && npm run lint && npm run build
```

Expected: both commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/api.ts frontend/components/AssignmentChat.tsx frontend/app/page.tsx
git commit -m "feat: add assignment chat UI"
```

## Task 5: Preserve Check-In as State Signal, Add Assignment Entry Point

**Files:**
- Modify: `backend/app/routers/checkin.py`
- Modify: `backend/app/agents/planning_agent.py`
- Test: `backend/tests/test_checkin_flow.py`

- [ ] **Step 1: Write failing test for proposal creation from check-in**

Append to `backend/tests/test_checkin_flow.py`:

```python
def test_checkin_response_includes_assignment_hint(client, monkeypatch) -> None:
    response = client.post(
        "/api/checkin",
        json={
            "status": "clear but busy",
            "did_today": "finished MCP integration",
            "stuck_on": "need to plan next phase",
            "anxiety": "",
            "raw": "Tomorrow I want a focus block for Phase 3.",
            "session_id": "default",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["assignment_hint"]["message"].startswith("可以继续让 WeatherFlow")
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
uv run --project backend pytest backend/tests/test_checkin_flow.py::test_checkin_response_includes_assignment_hint -q
```

Expected: FAIL because `assignment_hint` is not in the check-in response.

- [ ] **Step 3: Add assignment hint schema**

In `backend/app/routers/checkin.py`, add:

```python
class AssignmentHint(BaseModel):
    message: str
    suggested_prompt: str
```

Add this field to `CheckinResponse`:

```python
assignment_hint: AssignmentHint
```

Return it from `submit_checkin()`:

```python
assignment_hint=AssignmentHint(
    message="可以继续让 WeatherFlow 把这次 check-in 变成一个可确认的下一步。",
    suggested_prompt=_suggest_assignment_prompt(record, result.suggestion),
),
```

Add helper:

```python
def _suggest_assignment_prompt(checkin: CheckinRecord, suggestion: str) -> str:
    if checkin.stuck_on:
        return f"帮我把这个卡点变成一个可执行选择：{checkin.stuck_on}"
    if "专注" in suggestion or "focus" in suggestion.lower():
        return "帮我为这个建议安排一个可确认的 deep work block。"
    return "基于刚才的 check-in，给我 2 个下一步选择。"
```

- [ ] **Step 4: Run check-in test**

Run:

```bash
uv run --project backend pytest backend/tests/test_checkin_flow.py::test_checkin_response_includes_assignment_hint -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/checkin.py backend/tests/test_checkin_flow.py
git commit -m "feat: connect checkin to assignment chat"
```

## Task 6: Documentation and Product Framing

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Create: `docs/ASSIGNMENT_AGENT.md`

- [ ] **Step 1: Update README product shape**

In `README.md`, replace the product loop section with:

```markdown
WeatherFlow has three core loops:

```text
Daily loop:
check-in -> StateAgent -> ReflectionAgent -> PlanningAgent -> profile.md

Assignment loop:
chat assignment -> AssignmentAgent -> answer + confirmed ActionProposals

Developer rhythm loop:
GitHub MCP + Google Calendar MCP -> DevReviewAgent -> dashboard + profile context
```
```

- [ ] **Step 2: Add architecture doc section**

In `docs/ARCHITECTURE.md`, add:

```markdown
## Assignment Loop

The assignment loop is the user-directed workspace. It does not replace check-in;
it uses check-in, state, profile, and Dev Review as context. The loop returns a
short answer plus optional `ActionProposal` records. Proposals are confirmation-gated
and executed by `/api/actions/{proposal_id}/execute`.
```

- [ ] **Step 3: Add assignment agent doc**

Create `docs/ASSIGNMENT_AGENT.md`:

```markdown
# Assignment Agent

The Assignment Agent gives WeatherFlow a chat-first operating surface.

## Inputs

- current user message
- latest check-in and recent check-ins
- latest state snapshot
- profile.md
- latest Dev Review
- available safe tools

## Outputs

- assistant message
- zero or more ActionProposals

## Safety

The agent never executes side-effecting tools directly. It only creates proposals.
Users confirm proposals through the actions API.
```

- [ ] **Step 4: Run docs sanity checks**

Run:

```bash
rg -n "Assignment loop|Assignment Agent|ActionProposal" README.md docs/ARCHITECTURE.md docs/ASSIGNMENT_AGENT.md
```

Expected: output includes all three files.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/ARCHITECTURE.md docs/ASSIGNMENT_AGENT.md
git commit -m "docs: describe assignment agent loop"
```

## Task 7: Full Verification

**Files:**
- Verify only.

- [ ] **Step 1: Run backend quality gate**

Run:

```bash
make backend-lint backend-test
```

Expected:

```text
All checks passed!
119+ passed
```

The exact test count may increase after adding assignment tests.

- [ ] **Step 2: Run frontend quality gate**

Run:

```bash
cd frontend && npm run lint && npm run build
```

Expected: both commands exit 0.

- [ ] **Step 3: Run complete local check**

Run:

```bash
make check
```

Expected: backend lint/test, frontend lint, and frontend build all exit 0.

- [ ] **Step 4: Manual smoke test**

Start backend and frontend:

```bash
make dev-backend
make dev-frontend
```

Open dashboard and verify:

```text
1. Assignment Chat is visible on the dashboard.
2. Sending "帮我明天安排一个 deep work block" creates an assistant response.
3. With `GOOGLE_CALENDAR_ACCESS_TOKEN` or `GOOGLE_CALENDAR_TOKEN_FILE` configured, a focus block proposal appears.
4. Confirming the proposal calls /api/actions/{id}/execute.
5. The check-in page still submits and returns state/reflection/suggestion.
```

- [ ] **Step 5: Commit verification-only fixes if needed**

When verification changes files, commit those fixes:

```bash
git add backend frontend README.md docs
git commit -m "chore: verify assignment agent flow"
```

When verification changes no files, record the clean command output in the final handoff and do not create an empty commit.

## Self-Review

- Spec coverage: The plan covers the new chat assignment layer, safe proposal generation, confirmation-gated tool execution, check-in linkage, UI entry point, and docs.
- Placeholder scan: No unresolved implementation placeholders remain in task steps.
- Type consistency: `AssignmentIntent`, `AssignmentTurnCreate`, `AssignmentTurnRecord`, `AssignmentChatRequest`, and `AssignmentChatResponse` are introduced before use. `ActionProposal` remains the existing side-effect boundary.
- Scope check: This is one coherent first release. It deliberately excludes autonomous multi-step execution, direct tool execution from chat, background scheduling, and long-running agent jobs.
