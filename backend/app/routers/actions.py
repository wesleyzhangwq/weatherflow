"""Proposal execution endpoint — §12.5 + §7.4."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import get_settings
from app.mcp_client import MCPToolClient
from app.mcp_client.tool_registry import registry
from app.memory import event_log
from app.memory.derivations import run_derivations
from app.memory.schemas import ExecutedActionPayload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/actions", tags=["actions"])


class ConfirmIn(BaseModel):
    confirmed: bool = True


class ExecutedOut(BaseModel):
    proposal_id: str
    tool_name: str
    executed_action_id: str
    result: Any


def _derived_status(proposal_id: str) -> str:
    """Compute proposal status by walking related events (ADR D9 — lazy)."""
    rows = event_log.find_refs(
        ref_key="proposal", ref_value=proposal_id, limit=20
    )
    for r in rows:
        if r.type == "executed_action":
            return "confirmed"
        if r.type == "proposal_rejected":
            return "rejected"
        if r.type == "proposal_expired":
            return "expired"
    return "pending"


def _maybe_expire(proposal_id: str, created_at: str) -> bool:
    """Write proposal_expired event if past expiry; return True if newly expired."""
    s = get_settings()
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if datetime.now(timezone.utc) - created < timedelta(hours=s.proposal_expiry_hours):
        return False
    event_log.append(
        type="proposal_expired",
        payload={"proposal_id": proposal_id},
        refs={"proposal": proposal_id},
    )
    return True


@router.get("/proposals", response_model=List[dict])
def list_proposals(
    *, limit: int = 50, status: Optional[str] = None
) -> List[dict]:
    rows = event_log.list_recent(types=["proposal"], limit=limit)
    out: list[dict] = []
    for r in rows:
        current = _derived_status(r.id)
        if current == "pending":
            if _maybe_expire(r.id, r.timestamp):
                current = "expired"
        if status and current != status:
            continue
        out.append(
            {
                "id": r.id,
                "timestamp": r.timestamp,
                "tool_name": r.payload.get("tool_name"),
                "arguments": r.payload.get("arguments"),
                "rationale": r.payload.get("rationale"),
                "conversation_id": r.payload.get("conversation_id"),
                "status": current,
            }
        )
    return out


@router.get("/proposals/{proposal_id}", response_model=dict)
def get_proposal(proposal_id: str) -> dict:
    rec = event_log.get(proposal_id)
    if rec is None or rec.type != "proposal":
        raise HTTPException(status_code=404, detail="Proposal not found.")
    status = _derived_status(proposal_id)
    if status == "pending" and _maybe_expire(proposal_id, rec.timestamp):
        status = "expired"
    return {
        "id": rec.id,
        "timestamp": rec.timestamp,
        "tool_name": rec.payload.get("tool_name"),
        "arguments": rec.payload.get("arguments"),
        "rationale": rec.payload.get("rationale"),
        "conversation_id": rec.payload.get("conversation_id"),
        "status": status,
    }


@router.post("/{proposal_id}/execute", response_model=ExecutedOut)
async def execute_proposal(
    proposal_id: str, body: ConfirmIn, request: Request
) -> ExecutedOut:
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="confirmed=true required to execute.")

    rec = event_log.get(proposal_id)
    if rec is None or rec.type != "proposal":
        raise HTTPException(status_code=404, detail="Proposal not found.")
    status = _derived_status(proposal_id)
    if status == "pending" and _maybe_expire(proposal_id, rec.timestamp):
        status = "expired"
    if status != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal is already {status}.")

    tool_name = rec.payload.get("tool_name")
    tool = registry().get(tool_name) if tool_name else None
    if tool is None:
        raise HTTPException(status_code=400, detail=f"Tool {tool_name} not registered.")

    s = get_settings()
    command = (
        s.wf_calendar_mcp_command if tool.server == "calendar" else s.wf_github_mcp_command
    )
    client = MCPToolClient(command, timeout=s.wf_mcp_tool_timeout_seconds)
    try:
        async with client.session() as session:
            result = await client.call_tool(session, tool_name, rec.payload.get("arguments") or {})
    except Exception as exc:
        logger.exception("Proposal execution failed: %s", proposal_id)
        raise HTTPException(status_code=502, detail=f"Tool execution failed: {exc}") from exc

    payload = ExecutedActionPayload(
        proposal_id=proposal_id,
        tool_name=tool_name,
        result=result if isinstance(result, (dict, list, str, int, float, bool)) else str(result),
    )
    eid = event_log.append(
        type="executed_action",
        payload=payload.model_dump(),
        refs={"proposal": proposal_id},
    )

    # M1A.5 / ADR-004 D2: if the chat graph paused at this proposal (HITL
    # interrupt), resume it now that the write tool has executed.
    graph = getattr(request.app.state, "chat_graph", None)
    await _maybe_resume_graph(graph, rec.payload.get("conversation_id", ""), proposal_id, result)

    asyncio.create_task(run_derivations())

    return ExecutedOut(
        proposal_id=proposal_id,
        tool_name=tool_name,
        executed_action_id=eid,
        result=result,
    )


@router.post("/{proposal_id}/reject", response_model=dict)
def reject_proposal(proposal_id: str) -> dict:
    rec = event_log.get(proposal_id)
    if rec is None or rec.type != "proposal":
        raise HTTPException(status_code=404, detail="Proposal not found.")
    if _derived_status(proposal_id) != "pending":
        raise HTTPException(status_code=409, detail="Proposal is not pending.")
    eid = event_log.append(
        type="proposal_rejected",
        payload={"proposal_id": proposal_id},
        refs={"proposal": proposal_id},
    )
    return {"proposal_id": proposal_id, "rejection_event_id": eid}


async def _maybe_resume_graph(
    graph: Any, conversation_id: str, proposal_id: str, result: Any
) -> None:
    """Resume the chat graph paused at this proposal (ADR-004 D2, route A).

    The graph paused at human_review via interrupt(); state is in the SQLite
    checkpointer keyed by thread_id == conversation_id. We feed the execution
    result back via Command(resume=...), let the graph finish reasoning, and
    persist the continuation's final answer as an assistant chat_turn so the
    UI picks it up via /history (the original SSE stream is already closed).

    No-op when there is no graph or nothing is paused for this conversation.
    """
    if graph is None or not conversation_id:
        return

    from app.agents.graph.graph_runner import has_pending_interrupt, resume_chat

    if not await has_pending_interrupt(graph, conversation_id):
        return

    final_answer: Optional[str] = None
    try:
        async for ev in resume_chat(
            graph=graph,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
            execution_result=result,
        ):
            if ev.get("event") == "final_answer":
                try:
                    final_answer = json.loads(ev["data"]).get("content")
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
    except Exception:
        logger.exception("Graph resume after proposal %s failed", proposal_id)

    if final_answer:
        event_log.append(
            type="chat_turn",
            payload={
                "role": "assistant",
                "content": final_answer,
                "conversation_id": conversation_id,
            },
            refs={"conversation_id": conversation_id},
        )
