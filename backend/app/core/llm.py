"""Unified LLM client (OpenAI-compatible chat).

v1 only needs `.chat()`; embeddings were dropped along with qdrant.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional, Protocol, Sequence

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _record_llm_metrics(usage: dict[str, Any], latency_ms: float) -> None:
    """Best-effort: feed token usage + latency into the metrics collector (M1C.3)."""
    try:
        from app.observability.structured_logging import metrics

        metrics.increment("llm.calls")
        metrics.observe("llm.latency_ms", latency_ms)
        total = usage.get("total_tokens")
        if isinstance(total, (int, float)):
            metrics.observe("llm.tokens", float(total))
    except Exception:  # observability must never break the request path
        pass


class LLMClient(Protocol):
    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict[str, Any]] = None,
        disable_thinking: bool = False,
    ) -> str: ...

    async def chat_raw(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]: ...

    async def chat_raw_stream(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        on_delta: Any,
        model: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> dict[str, Any]: ...

    async def aclose(self) -> None: ...


class OpenAICompatibleClient:
    """Talks to any OpenAI-compatible /chat/completions gateway."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.openai_base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to /chat/completions and record the call as a Langfuse
        generation under the current run trace/span (ADR-004 D3) — or a
        standalone trace when no run is bound. Degrades to no-op without keys.
        """
        from app.observability.langfuse_integration import record_generation

        start = time.perf_counter()
        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        latency_ms = (time.perf_counter() - start) * 1000
        usage = data.get("usage") or {}
        record_generation(
            model=data.get("model", payload.get("model")),
            usage=usage,
            latency_ms=latency_ms,
        )
        _record_llm_metrics(usage, latency_ms)
        return data

    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict[str, Any]] = None,
        disable_thinking: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self._settings.chat_model,
            "messages": list(messages),
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format
        if disable_thinking and self._settings.supports_thinking_param:
            # MiniMax: turn reasoning OFF so structured output isn't preceded by
            # a long <think> block that shares (and exhausts) the token budget.
            # Gated so non-MiniMax gateways aren't sent an unknown param.
            payload["thinking"] = {"type": "disabled"}

        data = await self._post_chat(payload)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Unexpected chat response shape: {data!r}") from exc

    async def chat_raw(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Return the full assistant message dict (supports ``tool_calls``).

        Used by the graph act node (function-calling) which needs the raw
        message back rather than just content.
        """
        payload: dict[str, Any] = {
            "model": model or self._settings.chat_model,
            "messages": list(messages),
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        if response_format is not None:
            payload["response_format"] = response_format

        data = await self._post_chat(payload)
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Unexpected chat response shape: {data!r}") from exc

    async def chat_raw_stream(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        on_delta: Any,
        model: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> dict[str, Any]:
        """Stream /chat/completions, invoking ``on_delta(text)`` per visible
        content chunk, and return the fully-assembled assistant message.

        ``<think>…</think>`` spans (reasoning models inline them in content)
        are filtered out of the delta callbacks but kept in the returned
        message content, so downstream behaviour matches ``chat_raw``.
        Tool-call fragments are merged by index per the OpenAI stream shape.
        """
        payload: dict[str, Any] = {
            "model": model or self._settings.chat_model,
            "messages": list(messages),
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        from app.observability.langfuse_integration import record_generation

        start = time.perf_counter()
        content_parts: list[str] = []
        tool_calls_acc: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        think_filter = _ThinkStreamFilter()

        async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                chunk_raw = line[5:].strip()
                if chunk_raw == "[DONE]":
                    break
                try:
                    chunk = json.loads(chunk_raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk.get("usage"), dict):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content")
                if piece:
                    content_parts.append(piece)
                    visible = think_filter.feed(piece)
                    if visible:
                        try:
                            on_delta(visible)
                        except Exception:  # delta fan-out must never kill the call
                            pass
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    acc = tool_calls_acc.setdefault(
                        idx,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if tc.get("id"):
                        acc["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        acc["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        acc["function"]["arguments"] += fn["arguments"]

        tail = think_filter.flush()
        if tail:
            try:
                on_delta(tail)
            except Exception:
                pass

        latency_ms = (time.perf_counter() - start) * 1000
        record_generation(
            model=payload.get("model"), usage=usage, latency_ms=latency_ms
        )
        _record_llm_metrics(usage, latency_ms)

        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content_parts) or None,
        }
        if tool_calls_acc:
            message["tool_calls"] = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
        return message


class _ThinkStreamFilter:
    """Stateful filter that drops ``<think>…</think>`` spans from a token
    stream. Tags can be split across chunks, so a small carry buffer holds any
    trailing text that could be the start of a tag."""

    _OPEN, _CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._inside = False
        self._carry = ""

    def feed(self, piece: str) -> str:
        text = self._carry + piece
        self._carry = ""
        out: list[str] = []
        while text:
            if self._inside:
                pos = text.find(self._CLOSE)
                if pos == -1:
                    keep = self._partial_suffix_len(text, self._CLOSE)
                    self._carry = text[len(text) - keep:] if keep else ""
                    return "".join(out)
                text = text[pos + len(self._CLOSE):]
                self._inside = False
            else:
                pos = text.find(self._OPEN)
                if pos == -1:
                    keep = self._partial_suffix_len(text, self._OPEN)
                    if keep:
                        self._carry = text[len(text) - keep:]
                        out.append(text[: len(text) - keep])
                    else:
                        out.append(text)
                    return "".join(out)
                out.append(text[:pos])
                text = text[pos + len(self._OPEN):]
                self._inside = True
        return "".join(out)

    def flush(self) -> str:
        """Return any carried text that turned out not to be a tag prefix."""
        tail = "" if self._inside else self._carry
        self._carry = ""
        return tail

    @staticmethod
    def _partial_suffix_len(text: str, tag: str) -> int:
        for k in range(min(len(tag) - 1, len(text)), 0, -1):
            if text.endswith(tag[:k]):
                return k
        return 0


def build_llm_client(settings: Optional[Settings] = None) -> LLMClient:
    return OpenAICompatibleClient(settings or get_settings())


def get_request_llm() -> LLMClient:
    """Return the per-request shared LLM client, or a fresh one if unbound.

    Graph nodes call this instead of ``build_llm_client()`` so a single client
    (with its Langfuse trace context) is reused across all nodes of one run.

    Lifecycle: when a client is bound via ``tracing.run_context(llm=...)``, the
    run scope owns it — callers MUST NOT ``aclose()`` it. Only close a client
    you built yourself (the unbound fallback path).
    """
    from app.observability.tracing import get_request_llm as _bound

    client = _bound()
    return client if client is not None else build_llm_client()


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _strip_to_json(raw: str) -> str:
    """Tolerantly extract JSON from a model response.

    Reasoning models (MiniMax-M2, DeepSeek-R1, etc.) wrap content with
    <think>...</think> blocks even when response_format=json_object is set.
    Some models wrap the JSON in a markdown code fence. We strip both.
    """
    text = _THINK_RE.sub("", raw).strip()
    # A truncated reasoning block can leave an unterminated <think> with no
    # closing tag; drop everything from the last stray <think> onward.
    low = text.lower()
    if "<think>" in low:
        text = text[: low.rfind("<think>")].strip()
    # Strip code fences (```json ... ``` or ``` ... ```)
    text = text.strip("`").strip()
    if text.lower().startswith("json"):
        text = text[4:].strip()
    # If there's surrounding chat-y prose, try to extract the largest {...} blob.
    if not text.startswith("{"):
        m = _JSON_OBJECT_RE.search(text)
        if m:
            text = m.group(0)
    return text


_JSON_MAX_TOKENS_FLOOR = 4096


async def chat_json(
    llm: LLMClient,
    messages: Sequence[dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    disable_thinking: bool = True,
) -> Any:
    """Call the LLM in JSON mode and parse the result.

    Reasoning models (MiniMax-M3, DeepSeek-R1, …) prepend <think> blocks that
    share the token budget with the answer. For structured output we turn
    thinking OFF (where the gateway supports it) and floor ``max_tokens`` so the
    JSON tail is never truncated. On a parse failure (the classic truncation
    symptom) we retry once with double the budget.
    """
    budget = max(max_tokens or 0, _JSON_MAX_TOKENS_FLOOR)

    async def _attempt(mt: int) -> Any:
        raw = await llm.chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=mt,
            response_format={"type": "json_object"},
            disable_thinking=disable_thinking,
        )
        return json.loads(_strip_to_json(raw))

    try:
        return await _attempt(budget)
    except json.JSONDecodeError:
        logger.warning("chat_json parse failed (likely truncation); retrying with 2x tokens")
        return await _attempt(budget * 2)


__all__ = [
    "LLMClient",
    "OpenAICompatibleClient",
    "build_llm_client",
    "get_request_llm",
    "chat_json",
]
