"""GraphRunner — drive the compiled chat graph and adapt it to the SSE stream.

The chat graph is compiled once with an ``AsyncSqliteSaver`` checkpointer in the
app lifespan and passed in here. Write tools pause the graph via ``interrupt()``
(ADR-004 D2); ``resume_chat`` continues it after the user confirms a proposal,
keyed by ``thread_id == conversation_id``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Optional

from app.agents.graph.state import AgentState
from app.config import get_settings
from app.core.llm import LLMClient
from app.memory.schemas import HypothesisPayload

logger = logging.getLogger(__name__)


def _config(conversation_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": conversation_id}}


async def run_chat(
    *,
    graph: Any,
    llm: Optional[LLMClient] = None,  # reserved for P3 (shared client via run_context)
    user_message: str,
    hypothesis: HypothesisPayload,
    bundle_text: str,
    bundle_event_ids: list[str],
    conversation_id: str,
    trigger_event_id: str,
    user_id: Optional[str] = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run the chat graph, yielding SSE-compatible event dicts.

    SSE order follows v1 §10.2. If a write tool fires, the graph pauses at the
    human_review interrupt; we emit events through proposal_created and the
    stream ends (the continuation arrives later via /execute → resume → L1).
    """
    settings = get_settings()
    initial_state: AgentState = {
        "messages": [
            {"role": "system", "content": _build_system_prompt(hypothesis, bundle_text)},
            {"role": "user", "content": user_message},
        ],
        "conversation_id": conversation_id,
        "user_id": user_id or settings.default_user_id,
        "bundle_text": bundle_text,
        "bundle_event_ids": bundle_event_ids,
        "trigger_event_id": trigger_event_id,
        "hypothesis": hypothesis.model_dump(),
        "hypothesis_id": None,
        "plan": None,
        "observations": [],
        "proposals": [],
        "pending_proposal": None,
        "critic_verdict": None,
        "final_answer": None,
        "semantic_memories": [],
        "sse_events": [],
        "turn_count": 0,
        "max_turns": settings.rhythm_agent_max_turns,
    }

    try:
        result = await graph.ainvoke(initial_state, config=_config(conversation_id))
    except Exception as exc:
        logger.exception("Chat graph execution failed")
        yield _sse("error", {"message": str(exc)})
        return

    if result.get("__interrupt__"):
        logger.info("Chat graph paused on a proposal for conversation %s", conversation_id)

    for ev in result.get("sse_events", []):
        yield {"event": ev["event"], "data": json.dumps(ev["data"], ensure_ascii=False)}


async def resume_chat(
    *,
    graph: Any,
    conversation_id: str,
    proposal_id: str,
    execution_result: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Resume a chat graph paused at a write proposal (ADR-004 D2, route A).

    Feeds the tool execution result back via Command(resume=...); the graph
    re-enters human_review, appends the tool response, and continues acting →
    synthesize. Yields the continuation's final_answer (the caller persists it
    to L1 since the original SSE stream is already closed).
    """
    from langgraph.types import Command

    try:
        result = await graph.ainvoke(
            Command(resume={"proposal_id": proposal_id, "result": execution_result}),
            config=_config(conversation_id),
        )
    except Exception as exc:
        logger.exception("Chat graph resume failed for conversation %s", conversation_id)
        yield _sse("error", {"message": str(exc)})
        return

    final = result.get("final_answer")
    if final:
        yield _sse("final_answer", {"content": final})


async def has_pending_interrupt(graph: Any, conversation_id: str) -> bool:
    """True if the conversation's chat graph is paused mid-run (awaiting resume)."""
    try:
        snapshot = await graph.aget_state(_config(conversation_id))
        return bool(snapshot.next)
    except Exception:
        return False


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


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


__all__ = ["run_chat", "resume_chat", "has_pending_interrupt"]
