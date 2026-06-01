"""AgentState — shared state for the LangGraph chat graph.

Per weatherflow-architecture-v2.md §14.2, this TypedDict is the state that
flows through all graph nodes: load_context → recall_memory → plan → act →
criticize → synthesize.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict


class AgentState(TypedDict, total=False):
    """State shared across all nodes in the chat graph."""

    # --- conversation context ---
    messages: list[dict[str, Any]]
    conversation_id: str
    user_id: str

    # --- evidence bundle (assembled by load_context) ---
    bundle_text: str
    bundle_event_ids: list[str]
    trigger_event_id: str

    # --- hypothesis (first-turn or reused) ---
    hypothesis: Optional[dict[str, Any]]
    hypothesis_id: Optional[str]

    # --- planner output ---
    plan: Optional[str]

    # --- worker observations from tool calls ---
    observations: list[dict[str, Any]]

    # --- proposals created from write tool calls ---
    proposals: list[dict[str, Any]]

    # --- critic verdict ---
    critic_verdict: Optional[Literal["pass", "retry"]]

    # --- synthesis output ---
    final_answer: Optional[str]

    # --- L2.5 semantic recall (populated by recall_memory) ---
    semantic_memories: list[dict[str, Any]]

    # --- SSE event queue (collected during graph execution) ---
    sse_events: list[dict[str, Any]]

    # --- control ---
    turn_count: int
    max_turns: int


__all__ = ["AgentState"]
