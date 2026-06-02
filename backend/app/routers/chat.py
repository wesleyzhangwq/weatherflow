"""T4 Chat SSE router — see architecture-v1.md §10.1 / §12.4."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from typing import AsyncIterator

from typing import List

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agents.graph.graph_runner import run_chat
from app.core.llm import LLMClient
from app.core.orchestrator import generate_hypothesis
from app.memory import context_loader, event_log
from app.memory.derivations import run_derivations
from app.observability.structured_logging import metrics
from app.routers._deps import get_llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatStreamIn(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)


@router.post("/stream")
async def stream_chat(
    body: ChatStreamIn,
    request: Request,
    llm: LLMClient = Depends(get_llm),
) -> EventSourceResponse:
    graph = request.app.state.chat_graph
    return EventSourceResponse(_stream(body, llm, graph))


async def _stream(body: ChatStreamIn, llm: LLMClient, graph: object) -> AsyncIterator[dict]:
    start = time.perf_counter()
    # 1. Persist the user's chat_turn first (so the trigger event exists for bundle)
    turn_id = event_log.append(
        type="chat_turn",
        payload={
            "role": "user",
            "content": body.message,
            "conversation_id": body.conversation_id,
        },
        refs={"conversation_id": body.conversation_id},
    )

    # 2. Bundle assembly + hypothesis (first turn rule §5.5)
    try:
        bundle = await context_loader.load(
            trigger_event_id=turn_id, mode="chat"
        )
        yield _sse(
            "context_loaded",
            {"message": f"bundle loaded, {len(bundle.entries)} entries"},
        )
    except Exception as exc:
        logger.exception("Bundle assembly failed")
        yield _sse("error", {"message": f"bundle load failed: {exc}"})
        return

    try:
        is_first_turn = _is_first_turn(body.conversation_id)
        if is_first_turn:
            hyp_id, hyp = await generate_hypothesis(
                trigger_event_id=turn_id,
                mode="chat",
                llm=llm,
                conversation_id=body.conversation_id,
            )
            yield _sse("hypothesis_generated", {"id": hyp_id, **hyp.model_dump()})
        else:
            # Reuse the conversation's most recent hypothesis (§5.5 rule 3)
            existing = _latest_chat_hypothesis(body.conversation_id)
            if existing is None:
                # Shouldn't happen, but degrade gracefully.
                hyp_id, hyp = await generate_hypothesis(
                    trigger_event_id=turn_id,
                    mode="chat",
                    llm=llm,
                    conversation_id=body.conversation_id,
                )
                yield _sse("hypothesis_generated", {"id": hyp_id, **hyp.model_dump()})
            else:
                from app.memory.schemas import HypothesisPayload

                hyp = HypothesisPayload.model_validate(existing.payload)
    except Exception as exc:
        logger.exception("Hypothesis generation failed in chat flow")
        yield _sse("error", {"message": f"hypothesis failed: {exc}"})
        return

    # 3. Run chat agent (graph with v1 fallback)
    bundle_event_ids = [e.event_id for e in bundle.entries]

    try:
        async for ev in run_chat(
            graph=graph,
            llm=llm,
            user_message=body.message,
            hypothesis=hyp,
            bundle_text=bundle.render(),
            bundle_event_ids=bundle_event_ids,
            conversation_id=body.conversation_id,
            trigger_event_id=turn_id,
        ):
            # run_chat yields {"event": ..., "data": json_string} — pass through
            yield ev
    except Exception as exc:
        logger.exception("ChatAgent crashed")
        yield _sse("error", {"message": str(exc)})
        return

    # 4. Fan out derivations asynchronously (ADR D7 / ADR-004 D5 — fire-and-forget)
    metrics.observe("chat.latency_ms", (time.perf_counter() - start) * 1000)
    metrics.increment("chat.count")
    asyncio.create_task(run_derivations())


def _is_first_turn(conversation_id: str) -> bool:
    """A conversation is 'first turn' if there's exactly one user chat_turn
    so far (the one we just wrote)."""
    rows = event_log.find_refs(
        ref_key="conversation_id",
        ref_value=conversation_id,
        type_="chat_turn",
        limit=10,
    )
    user_turns = [r for r in rows if r.payload.get("role") == "user"]
    return len(user_turns) <= 1


def _latest_chat_hypothesis(conversation_id: str):
    rows = event_log.list_recent(types=["hypothesis"], limit=50)
    for r in rows:
        if r.payload.get("conversation_id") == conversation_id:
            return r
    return None


def _event_payload(ev) -> dict:
    data = asdict(ev)
    data.pop("event", None)
    return data


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


# --------------------------------------------------------------------------- history


class HistoryEntry(BaseModel):
    kind: str           # the SSE-equivalent event name ("reasoning_step", "proposal_created", ...)
    timestamp: str
    data: dict


@router.get("/{conversation_id}/history", response_model=List[HistoryEntry])
def get_history(conversation_id: str) -> List[HistoryEntry]:
    """Return all events belonging to a conversation in chronological order.

    Used by the frontend to rehydrate the chat view after navigation/reload.
    Maps L1 event types to the SSE event names the chat UI already knows how
    to render — keeps the renderer single-pathed.
    """
    rows = event_log.find_refs(
        ref_key="conversation_id",
        ref_value=conversation_id,
        limit=500,
    )
    # find_refs returns newest first; chat history wants chronological
    rows = sorted(rows, key=lambda r: r.timestamp)

    out: List[HistoryEntry] = []
    for r in rows:
        p = r.payload
        if r.type == "chat_turn":
            role = p.get("role")
            if role == "user":
                out.append(HistoryEntry(
                    kind="user_message",
                    timestamp=r.timestamp,
                    data={"content": p.get("content", "")},
                ))
            else:
                out.append(HistoryEntry(
                    kind="final_answer",
                    timestamp=r.timestamp,
                    data={"content": p.get("content", "")},
                ))
        elif r.type == "reasoning_step":
            out.append(HistoryEntry(
                kind="reasoning_step",
                timestamp=r.timestamp,
                data={"content": p.get("text", "")},
            ))
        elif r.type == "tool_call":
            out.append(HistoryEntry(
                kind="tool_call_finished",
                timestamp=r.timestamp,
                data={"tool_name": p.get("tool_name"), "status": "success"},
            ))
        elif r.type == "proposal":
            out.append(HistoryEntry(
                kind="proposal_created",
                timestamp=r.timestamp,
                data={
                    "proposal_id": r.id,
                    "tool_name": p.get("tool_name"),
                    "arguments": p.get("arguments") or {},
                    "rationale": p.get("rationale") or "",
                },
            ))
        elif r.type == "hypothesis":
            out.append(HistoryEntry(
                kind="hypothesis_generated",
                timestamp=r.timestamp,
                data={
                    "id": r.id,
                    "label": p.get("label"),
                    "confidence": p.get("confidence"),
                    "summary": p.get("summary"),
                },
            ))

    return out


@router.get("/conversations", response_model=List[dict])
def list_conversations(limit: int = 20) -> List[dict]:
    """Recent conversations (de-duped by conversation_id, sorted desc).

    Each entry returns a preview: first user message + last activity timestamp.
    Used by the frontend's conversation switcher (optional UX).
    """
    rows = event_log.list_recent(types=["chat_turn"], limit=500)
    seen: dict[str, dict] = {}
    for r in rows:
        cid = r.payload.get("conversation_id")
        if not cid:
            continue
        entry = seen.setdefault(cid, {
            "conversation_id": cid,
            "last_activity": r.timestamp,
            "first_user_message": None,
            "turn_count": 0,
        })
        entry["turn_count"] += 1
        if r.payload.get("role") == "user":
            # since rows are newest-first, the earliest user msg gets written last
            entry["first_user_message"] = r.payload.get("content", "")[:80]
        entry["last_activity"] = max(entry["last_activity"], r.timestamp)
    convs = sorted(seen.values(), key=lambda c: c["last_activity"], reverse=True)
    return convs[:limit]
