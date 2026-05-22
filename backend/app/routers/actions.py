"""Action execution endpoint — dispatches confirmed ActionProposals to MCP tools."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.memory.schemas import ActionProposal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/actions", tags=["actions"])

_PROPOSALS: dict[str, ActionProposal] = {}

_DESTRUCTIVE_TOOLS = {
    "calendar.delete_event",
    "calendar.update_event",
    "github.update_issue",
    "github.create_or_update_file",
}


class ActionConfirmation(BaseModel):
    confirmed: bool


class ActionExecuteResult(BaseModel):
    proposal_id: str
    tool_name: str
    result: dict[str, Any]


@router.post("/proposals", response_model=ActionProposal, status_code=201)
def create_proposal(proposal: ActionProposal) -> ActionProposal:
    _PROPOSALS[proposal.id] = proposal
    return proposal


@router.get("/proposals/{proposal_id}", response_model=ActionProposal)
def get_proposal(proposal_id: str) -> ActionProposal:
    proposal = _PROPOSALS.get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    return proposal


@router.post("/{proposal_id}/execute", response_model=ActionExecuteResult)
async def execute_action(
    proposal_id: str,
    confirmation: ActionConfirmation,
) -> ActionExecuteResult:
    proposal = _PROPOSALS.get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found.")

    if proposal.requires_confirmation and not confirmation.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Action requires explicit confirmation. Send confirmed=true.",
        )

    if proposal.tool_name in _DESTRUCTIVE_TOOLS and not confirmation.confirmed:
        raise HTTPException(
            status_code=400,
            detail=f"Tool '{proposal.tool_name}' is destructive and requires confirmed=true.",
        )

    settings = get_settings()
    if proposal.kind in ("calendar_event", "focus_block"):
        mcp_command = settings.wf_calendar_mcp_command
    else:
        mcp_command = settings.wf_github_mcp_command

    try:
        from app.mcp_client.client import MCPToolClient
        client = MCPToolClient(mcp_command, timeout=settings.wf_mcp_tool_timeout_seconds)
        async with client.session() as session:
            result = await client.call_tool(session, proposal.tool_name, proposal.tool_arguments)
    except Exception as exc:
        logger.exception("Action execution failed for proposal %s", proposal_id)
        raise HTTPException(
            status_code=500,
            detail=f"Action execution failed: {exc}",
        ) from exc

    del _PROPOSALS[proposal_id]

    return ActionExecuteResult(
        proposal_id=proposal_id,
        tool_name=proposal.tool_name,
        result=result if isinstance(result, dict) else {"raw": result},
    )
