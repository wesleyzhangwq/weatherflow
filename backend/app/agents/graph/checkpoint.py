"""Graph state checkpoint — in-memory store for paused graph executions.

When a write tool creates a Proposal, the graph pauses (interrupt pattern).
This module stores the paused state so it can be resumed after the user
confirms the proposal.

In production with langgraph installed, this would be backed by the
SQLite checkpointer. This module provides the same semantics for the
graph_runner adapter.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# In-memory store: conversation_id → paused AgentState
_paused_states: dict[str, dict[str, Any]] = {}


def save_paused_state(conversation_id: str, state: dict[str, Any]) -> None:
    """Save a paused graph state for later resume."""
    _paused_states[conversation_id] = state
    logger.info("Graph state paused for conversation %s", conversation_id)


def get_paused_state(conversation_id: str) -> Optional[dict[str, Any]]:
    """Retrieve a paused graph state, or None if not paused."""
    return _paused_states.get(conversation_id)


def clear_paused_state(conversation_id: str) -> None:
    """Remove a paused state (after resume or abandonment)."""
    _paused_states.pop(conversation_id, None)


def has_paused_state(conversation_id: str) -> bool:
    """Check if a conversation has a paused graph."""
    return conversation_id in _paused_states


__all__ = [
    "save_paused_state",
    "get_paused_state",
    "clear_paused_state",
    "has_paused_state",
]
