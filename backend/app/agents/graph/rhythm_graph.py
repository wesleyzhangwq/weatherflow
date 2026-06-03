"""Rhythm subgraph — LangGraph version of the T1/T2 hypothesis generation flow.

Per weatherflow-architecture-v2.md §14.8, this subgraph wraps:
    recall → hypothesize → verify_sources → persist

It shares the recall_memory node with the chat graph.
Falls back to the v1 orchestrator.generate_hypothesis() when langgraph unavailable.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.agents.graph.state import AgentState

logger = logging.getLogger(__name__)


async def recall_node(state: AgentState) -> dict[str, Any]:
    """Query semantic memory for relevant context. Shared with chat graph."""
    from app.agents.graph.chat_graph import recall_memory_node
    return await recall_memory_node(state)


async def hypothesize_node(state: AgentState) -> dict[str, Any]:
    """Generate a hypothesis using the RhythmAgent.

    Delegates to ContextLoader + RhythmAgent — the same v1 path the orchestrator
    uses, so the subgraph and the legacy flow produce identical hypotheses.
    """
    from app.agents.rhythm_agent import RhythmAgent
    from app.core.llm import build_llm_client
    from app.memory.context_loader import load as load_bundle

    llm = build_llm_client()
    agent = RhythmAgent(llm)
    try:
        bundle = await load_bundle(
            trigger_event_id=state["trigger_event_id"],
            mode=state.get("mode", "checkin"),
            user_id=state.get("user_id"),
        )
        hyp = await agent.generate(
            bundle=bundle,
            mode=state.get("mode", "checkin"),
            conversation_id=state.get("conversation_id"),
        )
        return {"hypothesis": hyp.model_dump()}
    except Exception:
        logger.exception("Hypothesis generation failed in rhythm subgraph")
        return {"hypothesis": None}
    finally:
        await llm.aclose()


async def verify_sources_node(state: AgentState) -> dict[str, Any]:
    """Validate that all evidence source_event_ids exist in L1.

    This is the same check as v1 §5.1 step 4.
    """
    from app.memory import event_log

    hyp = state.get("hypothesis")
    if not hyp:
        return {"critic_verdict": "retry"}

    evidence = hyp.get("evidence", [])
    for ev in evidence:
        sid = ev.get("source_event_id", "")
        if sid:
            rec = event_log.get(sid)
            if rec is None:
                logger.warning("verify_sources: source_event_id %s not in L1", sid)
                return {"critic_verdict": "retry"}

    return {"critic_verdict": "pass"}


async def persist_node(state: AgentState) -> dict[str, Any]:
    """Persist the hypothesis to L1. Returns the event id."""
    from app.memory import event_log

    hyp = state.get("hypothesis")
    if not hyp:
        return {"hypothesis_id": None}

    evidence_sources = [e.get("source_event_id", "") for e in hyp.get("evidence", [])]
    hyp_id = event_log.append(
        type="hypothesis",
        payload=hyp,
        user_id=state.get("user_id"),
        refs={
            "triggered_by": state["trigger_event_id"],
            "evidence_sources": evidence_sources,
        },
    )
    logger.info("Rhythm subgraph: hypothesis persisted id=%s label=%s", hyp_id, hyp.get("label"))
    return {"hypothesis_id": hyp_id}


def after_verify(state: AgentState) -> str:
    """Conditional edge: retry hypothesize if verification failed, else persist."""
    if state.get("critic_verdict") == "retry":
        return "hypothesize"
    return "persist"


def build_rhythm_graph() -> Any:
    """Build and compile the rhythm subgraph. Returns None if langgraph unavailable."""
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        logger.warning("langgraph not installed; rhythm subgraph unavailable")
        return None

    builder = StateGraph(AgentState)

    builder.add_node("recall", recall_node)
    builder.add_node("hypothesize", hypothesize_node)
    builder.add_node("verify_sources", verify_sources_node)
    builder.add_node("persist", persist_node)

    builder.set_entry_point("recall")
    builder.add_edge("recall", "hypothesize")
    builder.add_edge("hypothesize", "verify_sources")
    builder.add_conditional_edges(
        "verify_sources",
        after_verify,
        {"hypothesize": "hypothesize", "persist": "persist"},
    )
    builder.add_edge("persist", END)

    return builder.compile()


async def run_rhythm(
    *,
    trigger_event_id: str,
    mode: str,
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> tuple[Optional[str], Optional[dict]]:
    """Run the rhythm subgraph (or fall back to v1 orchestrator).

    Returns (hypothesis_id, hypothesis_payload) or (None, None) on failure.
    """
    from app.config import get_settings

    settings = get_settings()
    uid = user_id or settings.default_user_id

    graph = build_rhythm_graph()
    if graph is not None:
        initial_state: AgentState = {
            "messages": [],
            "conversation_id": conversation_id or "",
            "user_id": uid,
            "bundle_text": "",
            "bundle_event_ids": [],
            "trigger_event_id": trigger_event_id,
            "hypothesis": None,
            "hypothesis_id": None,
            "plan": None,
            "observations": [],
            "proposals": [],
            "critic_verdict": None,
            "final_answer": None,
            "semantic_memories": [],
            "sse_events": [],
            "turn_count": 0,
            "max_turns": 1,
        }
        # Inject mode for the rhythm subgraph
        initial_state["mode"] = mode  # type: ignore[assignment]

        # One trace per run (ADR-004 D3): bind a root trace so the hypothesize
        # LLM call attaches as a generation under `rhythm_run` instead of
        # floating as a standalone llm.chat trace.
        from app.observability import langfuse_integration as lf
        from app.observability.tracing import run_context

        root = lf.start_trace(
            "rhythm_run",
            {"mode": mode, "user_id": uid, "trigger_event_id": trigger_event_id},
        )
        try:
            with run_context(trace=root):
                result = await graph.ainvoke(initial_state)
            return result.get("hypothesis_id"), result.get("hypothesis")
        except Exception:
            logger.exception("Rhythm subgraph failed, falling back to v1")
            # Fall through to v1
        finally:
            lf.flush()

    # v1 fallback
    from app.core.llm import build_llm_client
    from app.core.orchestrator import generate_hypothesis

    llm = build_llm_client()
    try:
        hyp_id, hyp = await generate_hypothesis(
            trigger_event_id=trigger_event_id,
            mode=mode,
            llm=llm,
            user_id=uid,
            conversation_id=conversation_id,
        )
        return hyp_id, hyp.model_dump()
    except Exception:
        logger.exception("v1 generate_hypothesis also failed")
        return None, None
    finally:
        await llm.aclose()


__all__ = ["build_rhythm_graph", "run_rhythm"]
