"""GraphRunner — adapter between LangGraph graph and SSE event stream.

Bridges the chat_graph's execution with sse-starlette's event format.
Falls back to v1 ChatAgent when langgraph is not installed.

Supports proposal interrupt/resume: when a write tool creates a proposal,
the graph pauses and saves state. After user confirms, resume_chat() continues
from the saved state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any, AsyncIterator, Optional

from app.agents.chat_agent import (
    AgentEvent,
    ChatAgent,
    ErrorEvent,
    FinalAnswerEvent,
)
from app.agents.graph.chat_graph import build_chat_graph
from app.agents.graph.checkpoint import (
    clear_paused_state,
    get_paused_state,
    save_paused_state,
)
from app.agents.graph.state import AgentState
from app.config import get_settings
from app.core.llm import LLMClient
from app.memory.schemas import HypothesisPayload

logger = logging.getLogger(__name__)


async def run_chat(
    *,
    llm: LLMClient,
    user_message: str,
    hypothesis: HypothesisPayload,
    bundle_text: str,
    bundle_event_ids: list[str],
    conversation_id: str,
    trigger_event_id: str,
    user_id: Optional[str] = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run the chat agent, yielding SSE-compatible event dicts.

    Tries LangGraph graph first; falls back to v1 ChatAgent if unavailable.
    SSE event order follows v1 §10.2:
      context_loaded → hypothesis_generated → reasoning_step* →
      tool_call_started/finished/observation_summary* → proposal_created? → final_answer
    """
    settings = get_settings()

    # Try graph path
    graph = build_chat_graph()
    if graph is not None:
        async for ev in _run_graph(
            graph=graph,
            llm=llm,
            user_message=user_message,
            hypothesis=hypothesis,
            bundle_text=bundle_text,
            bundle_event_ids=bundle_event_ids,
            conversation_id=conversation_id,
            trigger_event_id=trigger_event_id,
            user_id=user_id or settings.default_user_id,
            max_turns=settings.rhythm_agent_max_turns,
        ):
            yield ev
    else:
        # v1 fallback
        async for ev in _run_v1(
            llm=llm,
            user_message=user_message,
            hypothesis=hypothesis,
            bundle_text=bundle_text,
            conversation_id=conversation_id,
            trigger_event_id=trigger_event_id,
        ):
            yield ev


async def _run_graph(
    *,
    graph: Any,
    llm: LLMClient,
    user_message: str,
    hypothesis: HypothesisPayload,
    bundle_text: str,
    bundle_event_ids: list[str],
    conversation_id: str,
    trigger_event_id: str,
    user_id: str,
    max_turns: int,
) -> AsyncIterator[dict[str, Any]]:
    """Execute via LangGraph graph, extracting SSE events from state."""
    initial_state: AgentState = {
        "messages": [
            {"role": "system", "content": _build_system_prompt(hypothesis, bundle_text)},
            {"role": "user", "content": user_message},
        ],
        "conversation_id": conversation_id,
        "user_id": user_id,
        "bundle_text": bundle_text,
        "bundle_event_ids": bundle_event_ids,
        "trigger_event_id": trigger_event_id,
        "hypothesis": hypothesis.model_dump(),
        "hypothesis_id": None,
        "plan": None,
        "observations": [],
        "proposals": [],
        "critic_verdict": None,
        "final_answer": None,
        "semantic_memories": [],
        "sse_events": [],
        "turn_count": 0,
        "max_turns": max_turns,
    }

    try:
        result = await graph.ainvoke(initial_state)
    except Exception as exc:
        logger.exception("Graph execution failed")
        yield _sse("error", {"message": str(exc)})
        return

    # Check if a proposal was created (interrupt pattern)
    proposals = result.get("proposals", [])
    if proposals and not result.get("final_answer"):
        # Graph paused at a proposal — save state for later resume
        save_paused_state(conversation_id, result)
        # Emit SSE events up to and including the proposal
        for ev in result.get("sse_events", []):
            yield {"event": ev["event"], "data": json.dumps(ev["data"], ensure_ascii=False)}
        return

    # Normal completion — emit all SSE events
    for ev in result.get("sse_events", []):
        yield {"event": ev["event"], "data": json.dumps(ev["data"], ensure_ascii=False)}


async def resume_chat(
    *,
    llm: LLMClient,
    conversation_id: str,
    proposal_id: str,
    execution_result: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Resume a paused graph after proposal execution.

    Called by the actions router after the user confirms a proposal.
    Continues the graph from the saved state with the tool result injected.
    """
    saved = get_paused_state(conversation_id)
    if saved is None:
        logger.warning("No paused state for conversation %s", conversation_id)
        return

    clear_paused_state(conversation_id)

    # Inject the execution result into the messages as a tool response
    messages = list(saved.get("messages", []))
    messages.append({
        "role": "tool",
        "tool_call_id": proposal_id,
        "content": json.dumps({"executed": True, "result": execution_result}, ensure_ascii=False)[:2000],
    })

    # Continue the graph from where it left off
    graph = build_chat_graph()
    if graph is not None:
        # Resume by running from the act node onward
        saved["messages"] = messages
        saved["final_answer"] = None  # clear so act continues

        try:
            result = await graph.ainvoke(saved)
        except Exception as exc:
            logger.exception("Graph resume failed")
            yield _sse("error", {"message": str(exc)})
            return

        for ev in result.get("sse_events", []):
            yield {"event": ev["event"], "data": json.dumps(ev["data"], ensure_ascii=False)}
    else:
        # v1 fallback: just emit a final answer based on the execution result
        yield _sse("final_answer", {"content": f"已执行操作 {proposal_id}。结果: {json.dumps(execution_result, ensure_ascii=False)[:500]}"})


async def _run_v1(
    *,
    llm: LLMClient,
    user_message: str,
    hypothesis: HypothesisPayload,
    bundle_text: str,
    conversation_id: str,
    trigger_event_id: str,
) -> AsyncIterator[dict[str, Any]]:
    """Execute via v1 ChatAgent (fallback when langgraph not installed)."""
    agent = ChatAgent(llm)
    async for ev in agent.run(
        user_message=user_message,
        hypothesis=hypothesis,
        bundle_text=bundle_text,
        conversation_id=conversation_id,
        parent_event_id=trigger_event_id,
    ):
        yield _sse(ev.event, _event_payload(ev))
        if isinstance(ev, (FinalAnswerEvent, ErrorEvent)):
            break


def _build_system_prompt(hypothesis: HypothesisPayload, bundle_text: str) -> str:
    import json as _json

    hyp_render = (
        f"标签: {hypothesis.label}\n"
        f"置信度: {hypothesis.confidence:.2f}\n"
        f"summary: {hypothesis.summary}\n"
        f"evidence: " + _json.dumps(
            [e.model_dump() for e in hypothesis.evidence], ensure_ascii=False
        )
    )
    return f"""你是 WeatherFlow 的驾驶舱 Agent。用户的当前节奏判断是：

{hyp_render}

下面是当前的 evidence bundle (你已经基于它给出了上面的 hypothesis)：

{bundle_text}

可用工具：read 类工具可以直接调用，write 类工具会被拦截转为 Proposal 等用户确认。

工作方式：
- 一步步思考；每个 reasoning_step 用一句话说明你打算做什么。
- 需要查询数据时调用 read 工具；需要建议用户做改动时调用 write 工具。
- 最后用中文给用户清晰的回答。

不要重复 hypothesis 的内容；用户已经看到它。聚焦于回答当前消息。
"""


def _event_payload(ev: AgentEvent) -> dict:
    data = asdict(ev)
    data.pop("event", None)
    return data


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


__all__ = ["run_chat", "resume_chat"]
