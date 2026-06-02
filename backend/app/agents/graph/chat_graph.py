"""ChatGraph — LangGraph state graph for the v2 chat agent.

Per weatherflow-architecture-v2.md §14.3, the graph topology is:

    load_context → recall_memory → plan → act → criticize → synthesize
                                          ↑         │
                                          └─ retry ─┘

The act node handles tool calls (read → observation, write → interrupt).
The critic node validates groundedness (source_event_id checks).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.agents.graph.state import AgentState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node implementations
# Each node takes AgentState and returns a partial state update (dict).
# ---------------------------------------------------------------------------


async def load_context_node(state: AgentState) -> dict[str, Any]:
    """Assemble the evidence bundle via ContextLoader.

    Populates: bundle_text, bundle_event_ids, trigger_event_id.
    """
    from app.memory import context_loader

    trigger_id = state["trigger_event_id"]
    mode = "chat"
    bundle = await context_loader.load(
        trigger_event_id=trigger_id,
        mode=mode,
        user_id=state.get("user_id"),
    )
    return {
        "bundle_text": bundle.render(),
        "bundle_event_ids": [e.event_id for e in bundle.entries],
    }


async def recall_memory_node(state: AgentState) -> dict[str, Any]:
    """Query semantic memory (L2.5) for relevant historical memories.

    Populates: semantic_memories.
    Falls back gracefully when mem0 is unavailable.
    """
    try:
        from app.memory.semantic.recall import recall_relevant

        memories = await recall_relevant(
            query=state.get("bundle_text", ""),
            user_id=state.get("user_id"),
        )
        return {"semantic_memories": memories}
    except (ImportError, Exception) as exc:
        logger.debug("Semantic recall unavailable, continuing without: %s", exc)
        return {"semantic_memories": []}


async def plan_node(state: AgentState) -> dict[str, Any]:
    """Decide next action based on current context.

    Uses the LLM to produce a plan string, which the act node will follow.
    On retry (from critic), includes the critic feedback in the plan.
    """
    from app.core.llm import build_llm_client

    llm = build_llm_client()

    messages = list(state.get("messages", []))

    # Build a planning prompt
    plan_prompt = (
        "Based on the conversation and evidence above, plan your next action. "
        "State what tool you need to call (if any) and why, or state that you "
        "have enough information to give a final answer. Be concise."
    )

    if state.get("critic_verdict") == "retry":
        plan_prompt += (
            "\n\n⚠️ The critic flagged your previous response for groundedness issues. "
            "Ensure every evidence reference uses a real source_event_id from the bundle."
        )

    messages.append({"role": "user", "content": plan_prompt})

    try:
        response = await llm.chat(messages, temperature=0.3, max_tokens=500)
        plan_text = _strip_think(response)
    except Exception as exc:
        logger.warning("Plan node LLM call failed: %s", exc)
        plan_text = "Provide final answer based on available evidence."

    await llm.aclose()
    return {"plan": plan_text, "critic_verdict": None}


async def act_node(state: AgentState) -> dict[str, Any]:
    """Execute tool calls or produce a final answer (the worker node).

    This is the main workhorse — equivalent to the v1 ReAct loop body.
    Handles: read tools → observation, write tools → proposal, final answer.
    """
    import json

    from app.core.llm import build_llm_client
    from app.mcp_client.dispatcher import (
        ErrorResult,
        ObservationResult,
        ProposalResult,
        dispatch,
    )
    from app.mcp_client.tool_registry import registry

    llm = build_llm_client()
    tools_schemas = registry().openai_tool_schemas()
    messages = list(state.get("messages", []))

    # Inject plan context
    if state.get("plan"):
        messages.append({
            "role": "system",
            "content": f"Your plan: {state['plan']}",
        })

    turn_count = state.get("turn_count", 0)
    observations = list(state.get("observations", []))
    proposals = list(state.get("proposals", []))
    sse_events = list(state.get("sse_events", []))

    # One LLM call per act invocation. Reuse the shared LLMClient (which carries
    # auth/base_url/timeouts + Langfuse tracing) via chat_raw, which returns the
    # full assistant message so we can read tool_calls.
    try:
        msg = await llm.chat_raw(
            messages,
            temperature=0.4,
            tools=tools_schemas,
            tool_choice="auto",
        )
    except Exception as exc:
        logger.exception("LLM call failed in act node")
        sse_events.append({"event": "error", "data": {"message": str(exc)}})
        await llm.aclose()
        return {
            "sse_events": sse_events,
            "final_answer": f"（LLM 调用失败: {exc}）",
            "turn_count": turn_count + 1,
        }

    raw_content = (msg.get("content") or "").strip()
    content = _strip_think(raw_content)
    tool_calls = msg.get("tool_calls") or []

    # If only content (no tools), this is the final answer
    if content and not tool_calls:
        sse_events.append({"event": "final_answer", "data": {"content": content}})
        messages.append({"role": "assistant", "content": content})
        await llm.aclose()
        return {
            "messages": messages,
            "final_answer": content,
            "sse_events": sse_events,
            "turn_count": turn_count + 1,
            "observations": observations,
            "proposals": proposals,
        }

    # If content + tool calls, emit reasoning step
    if content and tool_calls:
        sse_events.append({"event": "reasoning_step", "data": {"content": content}})

    # Execute tool calls
    messages.append({"role": "assistant", "content": content or None, "tool_calls": tool_calls})
    conversation_id = state.get("conversation_id", "")
    parent_event_id = state.get("trigger_event_id", "")

    for tc in tool_calls:
        fn = tc.get("function") or {}
        tool_name = fn.get("name", "")
        args_raw = fn.get("arguments", "{}")
        try:
            arguments = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
        except json.JSONDecodeError:
            arguments = {}

        sse_events.append({"event": "tool_call_started", "data": {"tool_name": tool_name, "arguments": arguments}})

        result = await dispatch(
            tool_name=tool_name,
            arguments=arguments,
            conversation_id=conversation_id,
            parent_event_id=parent_event_id,
            rationale=content or "(no reasoning provided)",
        )

        if isinstance(result, ObservationResult):
            sse_events.append({"event": "tool_call_finished", "data": {"tool_name": tool_name, "status": "success"}})
            obs_text = _summarize_observation(result.result)
            sse_events.append({"event": "observation_summary", "data": {"content": obs_text}})
            observations.append({"tool_name": tool_name, "result": result.result})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": json.dumps(result.result, ensure_ascii=False)[:2000],
            })
        elif isinstance(result, ProposalResult):
            sse_events.append({"event": "tool_call_finished", "data": {"tool_name": tool_name, "status": "proposal"}})
            sse_events.append({
                "event": "proposal_created",
                "data": {
                    "proposal_id": result.proposal_id,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "rationale": result.rationale,
                },
            })
            proposals.append({"proposal_id": result.proposal_id, "tool_name": tool_name})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": json.dumps({"proposal_created": result.proposal_id}, ensure_ascii=False),
            })
        else:
            sse_events.append({"event": "tool_call_finished", "data": {"tool_name": tool_name, "status": "error"}})
            err_msg = result.message if isinstance(result, ErrorResult) else "unknown error"
            sse_events.append({"event": "error", "data": {"message": err_msg}})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": json.dumps({"error": err_msg}, ensure_ascii=False),
            })

    await llm.aclose()

    return {
        "messages": messages,
        "observations": observations,
        "proposals": proposals,
        "sse_events": sse_events,
        "turn_count": turn_count + 1,
    }


async def criticize_node(state: AgentState) -> dict[str, Any]:
    """Validate groundedness: check that all evidence source_event_ids exist in the bundle.

    Per v2 §14.6, this is the runtime self-check version of v1 §5.1 step 4.
    """
    final_answer = state.get("final_answer", "")
    bundle_event_ids = set(state.get("bundle_event_ids", []))
    hypothesis = state.get("hypothesis")

    # If no final answer yet, this is a mid-loop check — pass through
    if not final_answer and not hypothesis:
        return {"critic_verdict": "pass"}

    # Check hypothesis evidence references
    if hypothesis:
        evidence_list = hypothesis.get("evidence", [])
        for ev in evidence_list:
            sid = ev.get("source_event_id", "")
            if sid and sid not in bundle_event_ids:
                logger.warning(
                    "Critic: evidence source_event_id %s not in bundle (verdict=retry)",
                    sid,
                )
                return {"critic_verdict": "retry"}

    return {"critic_verdict": "pass"}


async def synthesize_node(state: AgentState) -> dict[str, Any]:
    """Produce final answer if not already set (handles the case where
    act exhausted max turns without a content-only response)."""
    if state.get("final_answer"):
        return {}

    from app.core.llm import build_llm_client

    llm = build_llm_client()
    messages = list(state.get("messages", []))
    messages.append({
        "role": "user",
        "content": "请给出你的最终回答。基于以上所有讨论和工具调用结果，用中文简洁回答。",
    })

    try:
        response = await llm.chat(messages, temperature=0.4, max_tokens=1000)
        answer = _strip_think(response)
        sse_events = list(state.get("sse_events", []))
        sse_events.append({"event": "final_answer", "data": {"content": answer}})
        return {"final_answer": answer, "sse_events": sse_events}
    except Exception as exc:
        logger.exception("Synthesize node failed")
        return {"final_answer": f"（生成回答失败: {exc}）"}
    finally:
        await llm.aclose()


# ---------------------------------------------------------------------------
# Conditional edge functions
# ---------------------------------------------------------------------------


def should_continue_act(state: AgentState) -> str:
    """Decide whether to continue tool calls, run critic, or synthesize."""
    if state.get("final_answer"):
        return "synthesize"
    if state.get("turn_count", 0) >= state.get("max_turns", 8):
        return "synthesize"
    return "criticize"


def after_critic(state: AgentState) -> str:
    """Decide whether to retry (re-plan) or synthesize."""
    if state.get("critic_verdict") == "retry":
        # Only retry once — check if we've already retried
        turn_count = state.get("turn_count", 0)
        if turn_count <= 1:
            return "plan"
    return "synthesize"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_chat_graph(checkpointer: Any = None) -> Any:
    """Build and compile the LangGraph chat graph.

    Returns a compiled graph ready to invoke. If langgraph is not installed,
    returns None (caller should fall back to v1 behavior).
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        logger.warning("langgraph not installed; chat graph unavailable")
        return None

    builder = StateGraph(AgentState)

    # Add nodes
    builder.add_node("load_context", load_context_node)
    builder.add_node("recall_memory", recall_memory_node)
    builder.add_node("plan", plan_node)
    builder.add_node("act", act_node)
    builder.add_node("criticize", criticize_node)
    builder.add_node("synthesize", synthesize_node)

    # Edges
    builder.set_entry_point("load_context")
    builder.add_edge("load_context", "recall_memory")
    builder.add_edge("recall_memory", "plan")
    builder.add_edge("plan", "act")

    # Conditional: act → criticize or synthesize
    builder.add_conditional_edges(
        "act",
        should_continue_act,
        {"synthesize": "synthesize", "criticize": "criticize"},
    )

    # Conditional: criticize → plan (retry) or synthesize
    builder.add_conditional_edges(
        "criticize",
        after_critic,
        {"plan": "plan", "synthesize": "synthesize"},
    )

    builder.add_edge("synthesize", END)

    return builder.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_think(text: str) -> str:
    """Strip <think>...</think> blocks from reasoning-model output."""
    return _THINK_RE.sub("", text or "").strip()


def _summarize_observation(result: Any) -> str:
    if isinstance(result, dict):
        keys = list(result.keys())[:5]
        return f"返回 dict，键: {keys}"
    if isinstance(result, list):
        return f"返回 list，长度 {len(result)}"
    return str(result)[:200]


__all__ = [
    "build_chat_graph",
    "load_context_node",
    "recall_memory_node",
    "plan_node",
    "act_node",
    "criticize_node",
    "synthesize_node",
]
