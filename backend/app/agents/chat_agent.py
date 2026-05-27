"""ChatAgent — ReAct loop for T4.

Uses OpenAI function-calling (ADR D20). Each step yields a typed event so the
SSE router can stream it to the client. The Hypothesis used here is produced
*before* the loop starts (ADR D21) and injected into the system message.

Per architecture-v1.md §5.5:
- The first hypothesis in a conversation goes onto the main card stack
- Subsequent reasoning may produce further hypothesis events, but the stack
  query (hypotheses_view) de-dupes by conversation_id so only the latest one
  per conversation appears on the homepage.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx

from app.config import Settings, get_settings
from app.core.llm import LLMClient
from app.mcp_client.dispatcher import (
    ErrorResult,
    ObservationResult,
    ProposalResult,
    dispatch,
)
from app.mcp_client.tool_registry import registry
from app.memory import event_log
from app.memory.schemas import (
    HypothesisPayload,
    ReasoningStepPayload,
)

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_think(text: str) -> str:
    """Strip <think>...</think> blocks from reasoning-model output.

    OpenAI function-calling lets us see the model's pre-tool reasoning in
    message.content; for reasoning models (MiniMax-M2, DeepSeek-R1, etc.)
    this includes a verbose <think> block. We don't want that polluting L1
    or the chat UI — strip it here.
    """
    return _THINK_RE.sub("", text or "").strip()


# --------------------------------------------------------------------------- SSE event types


@dataclass
class ReasoningStepEvent:
    event: str = "reasoning_step"
    content: str = ""


@dataclass
class ToolCallStartedEvent:
    tool_name: str
    arguments: dict
    event: str = "tool_call_started"


@dataclass
class ToolCallFinishedEvent:
    tool_name: str
    status: str  # "success" | "error"
    event: str = "tool_call_finished"


@dataclass
class ObservationSummaryEvent:
    content: str
    event: str = "observation_summary"


@dataclass
class ProposalCreatedEvent:
    proposal_id: str
    tool_name: str
    arguments: dict
    rationale: str
    event: str = "proposal_created"


@dataclass
class FinalAnswerEvent:
    content: str
    event: str = "final_answer"


@dataclass
class ErrorEvent:
    message: str
    event: str = "error"


AgentEvent = (
    ReasoningStepEvent
    | ToolCallStartedEvent
    | ToolCallFinishedEvent
    | ObservationSummaryEvent
    | ProposalCreatedEvent
    | FinalAnswerEvent
    | ErrorEvent
)


# --------------------------------------------------------------------------- system prompt


def _system_prompt(hypothesis: HypothesisPayload, bundle_text: str) -> str:
    hyp_render = (
        f"标签: {hypothesis.label}\n"
        f"置信度: {hypothesis.confidence:.2f}\n"
        f"summary: {hypothesis.summary}\n"
        f"evidence: " + json.dumps(
            [e.model_dump() for e in hypothesis.evidence], ensure_ascii=False
        )
    )
    return f"""你是 WeatherFlow 的驾驶舱 Agent。用户的当前节奏判断是：

{hyp_render}

下面是当前的 evidence bundle (你已经基于它给出了上面的 hypothesis)：

{bundle_text}

可用工具：read 类工具可以直接调用，结果会作为 observation 返回。write 类工具会被系统拦截转为 Proposal 等用户确认（即：你"调用"它们时不会真的执行写操作，只是生成一条建议）。

工作方式：
- 一步步思考；每个 reasoning_step 用一句话清晰说明你打算做什么。
- 需要查询数据时调用 read 工具；需要建议用户做改动时调用 write 工具（会被自动转成 Proposal）。
- 最后用一段中文给用户清晰的回答。如果已经生成了 Proposal，最终回答应该提到"我已为你拟好了 X，确认后执行"。

不要重复 hypothesis 的内容；用户已经看到它。聚焦于回答当前消息。
"""


# --------------------------------------------------------------------------- ReAct loop


class ChatAgent:
    def __init__(self, llm: LLMClient, settings: Optional[Settings] = None) -> None:
        self._llm = llm
        self._settings = settings or get_settings()

    async def run(
        self,
        *,
        user_message: str,
        hypothesis: HypothesisPayload,
        bundle_text: str,
        conversation_id: str,
        parent_event_id: str,
    ) -> AsyncIterator[AgentEvent]:
        tools_schemas = registry().openai_tool_schemas()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _system_prompt(hypothesis, bundle_text)},
            {"role": "user", "content": user_message},
        ]

        for step in range(self._settings.rhythm_agent_max_turns):
            try:
                msg = await self._chat_call(messages, tools=tools_schemas)
            except Exception as exc:
                logger.exception("LLM chat call failed at step %d", step)
                yield ErrorEvent(message=str(exc))
                return

            raw_content = (msg.get("content") or "").strip()
            content = _strip_think(raw_content)
            tool_calls = msg.get("tool_calls") or []

            if content and tool_calls:
                # Some models emit both a partial reasoning message and tool_calls.
                yield ReasoningStepEvent(content=content)
                event_log.append(
                    type="reasoning_step",
                    payload=ReasoningStepPayload(text=content, conversation_id=conversation_id).model_dump(),
                    refs={"parent": parent_event_id, "conversation_id": conversation_id},
                )
            elif content and not tool_calls:
                # Terminating final answer.
                yield FinalAnswerEvent(content=content)
                event_log.append(
                    type="chat_turn",
                    payload={"role": "assistant", "content": content, "conversation_id": conversation_id},
                    refs={"parent": parent_event_id, "conversation_id": conversation_id},
                )
                return

            if not tool_calls:
                # Empty answer; rare but possible. End politely.
                yield FinalAnswerEvent(content="（暂无更多想法。）")
                return

            # Add assistant message with tool calls to history, then execute each call.
            messages.append({"role": "assistant", "content": content or None, "tool_calls": tool_calls})

            for tc in tool_calls:
                fn = tc.get("function") or {}
                tool_name = fn.get("name", "")
                args_raw = fn.get("arguments", "{}")
                try:
                    arguments = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                except json.JSONDecodeError:
                    arguments = {}

                yield ToolCallStartedEvent(tool_name=tool_name, arguments=arguments)

                result = await dispatch(
                    tool_name=tool_name,
                    arguments=arguments,
                    conversation_id=conversation_id,
                    parent_event_id=parent_event_id,
                    rationale=content or "(no reasoning provided)",
                )

                if isinstance(result, ObservationResult):
                    yield ToolCallFinishedEvent(tool_name=tool_name, status="success")
                    observation_text = _summarize_observation(result.result)
                    yield ObservationSummaryEvent(content=observation_text)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": json.dumps(result.result, ensure_ascii=False)[:2000],
                        }
                    )
                elif isinstance(result, ProposalResult):
                    yield ToolCallFinishedEvent(tool_name=tool_name, status="proposal")
                    yield ProposalCreatedEvent(
                        proposal_id=result.proposal_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        rationale=result.rationale,
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": json.dumps(
                                {
                                    "proposal_created": result.proposal_id,
                                    "note": "等待用户确认；不要再次发起同一调用。",
                                },
                                ensure_ascii=False,
                            ),
                        }
                    )
                else:
                    yield ToolCallFinishedEvent(tool_name=tool_name, status="error")
                    yield ErrorEvent(message=result.message if isinstance(result, ErrorResult) else "unknown error")
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": json.dumps({"error": getattr(result, "message", "unknown")}, ensure_ascii=False),
                        }
                    )

        # Exhausted max turns
        yield FinalAnswerEvent(content="（思考超出步数上限。先返回当前结论。）")

    async def _chat_call(self, messages: list[dict[str, Any]], *, tools: list[dict]) -> dict[str, Any]:
        """Direct call to /chat/completions because we need raw tool_calls back."""
        s = self._settings
        client = httpx.AsyncClient(
            base_url=s.openai_base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {s.openai_api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        try:
            payload = {
                "model": s.chat_model,
                "messages": messages,
                "temperature": s.chat_temperature,
                "tools": tools,
                "tool_choice": "auto",
            }
            resp = await client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]
        finally:
            await client.aclose()


def _summarize_observation(result: Any) -> str:
    if isinstance(result, dict):
        keys = list(result.keys())[:5]
        return f"返回 dict，键: {keys}"
    if isinstance(result, list):
        return f"返回 list，长度 {len(result)}"
    return str(result)[:200]


__all__ = [
    "AgentEvent",
    "ChatAgent",
    "ErrorEvent",
    "FinalAnswerEvent",
    "ObservationSummaryEvent",
    "ProposalCreatedEvent",
    "ReasoningStepEvent",
    "ToolCallFinishedEvent",
    "ToolCallStartedEvent",
]
