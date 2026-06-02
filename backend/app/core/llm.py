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
        """POST to /chat/completions, wrapped in a Langfuse trace (M1C.1).

        Records model / token usage / latency. Tracing degrades to a no-op
        when Langfuse is unavailable, so this never breaks the call path.
        """
        from app.observability.langfuse_integration import trace

        start = time.perf_counter()
        with trace("llm.chat", {"model": payload.get("model")}) as span:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            latency_ms = (time.perf_counter() - start) * 1000
            usage = data.get("usage") or {}
            span.update(
                output={
                    "usage": usage,
                    "latency_ms": round(latency_ms, 1),
                    "model": data.get("model", payload.get("model")),
                }
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

        Used by function-calling paths (graph act node, v2 ChatAgent) that need
        the raw message back rather than just content.
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


def build_llm_client(settings: Optional[Settings] = None) -> LLMClient:
    return OpenAICompatibleClient(settings or get_settings())


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _strip_to_json(raw: str) -> str:
    """Tolerantly extract JSON from a model response.

    Reasoning models (MiniMax-M2, DeepSeek-R1, etc.) wrap content with
    <think>...</think> blocks even when response_format=json_object is set.
    Some models wrap the JSON in a markdown code fence. We strip both.
    """
    text = _THINK_RE.sub("", raw).strip()
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


async def chat_json(
    llm: LLMClient,
    messages: Sequence[dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
) -> Any:
    raw = await llm.chat(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    cleaned = _strip_to_json(raw)
    return json.loads(cleaned)


__all__ = ["LLMClient", "OpenAICompatibleClient", "build_llm_client", "chat_json"]
