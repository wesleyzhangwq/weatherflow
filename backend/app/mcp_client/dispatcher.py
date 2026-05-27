"""Dispatcher — turns an Agent's tool-call intent into either an
observation or a Proposal (ADR D19).

This is the only place that decides whether a tool actually runs (read) or
gets deferred behind a user-confirmation step (write). All paths write to L1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Union

from app.config import get_settings
from app.mcp_client import MCPToolClient
from app.mcp_client.tool_registry import Tool, registry
from app.memory import event_log
from app.memory.schemas import ProposalPayload, ToolCallPayload

logger = logging.getLogger(__name__)


@dataclass
class ObservationResult:
    tool_name: str
    arguments: dict
    result: Any
    tool_call_event_id: str


@dataclass
class ProposalResult:
    tool_name: str
    arguments: dict
    proposal_id: str
    rationale: str


@dataclass
class ErrorResult:
    tool_name: str
    message: str


DispatchResult = Union[ObservationResult, ProposalResult, ErrorResult]


class ToolNotAvailable(Exception):
    pass


async def dispatch(
    *,
    tool_name: str,
    arguments: dict,
    conversation_id: str,
    parent_event_id: Optional[str] = None,
    rationale: str = "",
) -> DispatchResult:
    tool = registry().get(tool_name)
    if tool is None:
        # destructive tools fall here too — they're not registered (ADR D18)
        return ErrorResult(tool_name=tool_name, message=f"Tool not available: {tool_name}")

    if tool.mode == "read":
        return await _dispatch_read(tool, arguments, conversation_id, parent_event_id)
    if tool.mode == "write":
        return _dispatch_write(tool, arguments, conversation_id, parent_event_id, rationale)

    # belt-and-suspenders: should never reach (destructive can't be in registry)
    return ErrorResult(tool_name=tool_name, message=f"Unsupported tool mode: {tool.mode}")


async def _dispatch_read(
    tool: Tool,
    arguments: dict,
    conversation_id: str,
    parent_event_id: Optional[str],
) -> DispatchResult:
    s = get_settings()
    command = (
        s.wf_calendar_mcp_command if tool.server == "calendar" else s.wf_github_mcp_command
    )
    client = MCPToolClient(command, timeout=s.wf_mcp_tool_timeout_seconds)
    try:
        async with client.session() as session:
            result = await client.call_tool(session, tool.name, arguments)
    except Exception as exc:
        logger.exception("Tool %s failed", tool.name)
        return ErrorResult(tool_name=tool.name, message=str(exc))

    refs = {"conversation_id": conversation_id}
    if parent_event_id:
        refs["parent"] = parent_event_id
    payload = ToolCallPayload(
        tool_name=tool.name,
        arguments=arguments,
        result=result if isinstance(result, (dict, list, str, int, float, bool)) else str(result),
        conversation_id=conversation_id,
    )
    event_id = event_log.append(type="tool_call", payload=payload.model_dump(), refs=refs)
    return ObservationResult(
        tool_name=tool.name,
        arguments=arguments,
        result=result,
        tool_call_event_id=event_id,
    )


def _dispatch_write(
    tool: Tool,
    arguments: dict,
    conversation_id: str,
    parent_event_id: Optional[str],
    rationale: str,
) -> DispatchResult:
    payload = ProposalPayload(
        tool_name=tool.name,
        arguments=arguments,
        rationale=rationale or "Proposed by the rhythm agent based on the current conversation.",
        status="pending",
        conversation_id=conversation_id,
    )
    refs = {"conversation_id": conversation_id}
    if parent_event_id:
        refs["parent"] = parent_event_id
    proposal_id = event_log.append(type="proposal", payload=payload.model_dump(), refs=refs)
    return ProposalResult(
        tool_name=tool.name,
        arguments=arguments,
        proposal_id=proposal_id,
        rationale=payload.rationale,
    )


__all__ = [
    "DispatchResult",
    "ErrorResult",
    "ObservationResult",
    "ProposalResult",
    "ToolNotAvailable",
    "dispatch",
]
