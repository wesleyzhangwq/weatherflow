"""Unified LLM client (OpenAI-compatible chat).

v1 only needs `.chat()`; embeddings were dropped along with qdrant.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Protocol, Sequence

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


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

        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
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
