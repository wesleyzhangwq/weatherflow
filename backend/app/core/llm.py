"""Unified LLM client.

Provider strategy:
- Default: OpenAI-compatible HTTP API (any gateway via OPENAI_BASE_URL).
- Anthropic adapter is a stub for future swap. Agents must depend ONLY on the
  ``LLMClient`` protocol so swapping a provider does not require touching them.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional, Protocol, Sequence

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public protocol the rest of the app depends on
# ---------------------------------------------------------------------------
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

    async def embed(
        self, texts: Sequence[str], *, model: Optional[str] = None
    ) -> List[List[float]]: ...

    async def aclose(self) -> None: ...


# ---------------------------------------------------------------------------
# OpenAI-compatible client (the only one wired up in MVP)
# ---------------------------------------------------------------------------
class OpenAICompatibleClient:
    """Talks to any OpenAI-compatible HTTP gateway.

    Endpoints used:
      POST  {base}/chat/completions
      POST  {base}/embeddings
    """

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
        embed_base = (settings.embedding_base_url or settings.openai_base_url).rstrip("/")
        embed_key = settings.embedding_api_key or settings.openai_api_key
        self._embed_client = httpx.AsyncClient(
            base_url=embed_base,
            headers={
                "Authorization": f"Bearer {embed_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
        await self._embed_client.aclose()

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

    async def embed(
        self, texts: Sequence[str], *, model: Optional[str] = None
    ) -> List[List[float]]:
        if not texts:
            return []
        payload = {
            "model": model or self._settings.embedding_model,
            "input": list(texts),
        }
        resp = await self._embed_client.post("/embeddings", json=payload)
        resp.raise_for_status()
        data = resp.json()
        try:
            return [row["embedding"] for row in data["data"]]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"Unexpected embed response shape: {data!r}") from exc


# ---------------------------------------------------------------------------
# Anthropic adapter (RESERVED — not wired up; kept here so agents stay stable)
# ---------------------------------------------------------------------------
class AnthropicAdapter:
    """Future home for Anthropic Messages API.

    Intentionally a stub. Filling this in must not require any change to agents.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def chat(self, *args: Any, **kwargs: Any) -> str:  # pragma: no cover
        raise NotImplementedError("AnthropicAdapter.chat is reserved for a future iteration")

    async def embed(self, *args: Any, **kwargs: Any) -> List[List[float]]:  # pragma: no cover
        raise NotImplementedError(
            "Anthropic does not expose embeddings; route to OPENAI for embeddings."
        )

    async def aclose(self) -> None:  # pragma: no cover
        return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def build_llm_client(settings: Optional[Settings] = None) -> LLMClient:
    settings = settings or get_settings()
    return OpenAICompatibleClient(settings)


# ---------------------------------------------------------------------------
# JSON helper — agents often want strict JSON back
# ---------------------------------------------------------------------------
async def chat_json(
    llm: LLMClient,
    messages: Sequence[dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
) -> Any:
    """Ask the LLM for strict JSON. Falls back to best-effort parse if the
    provider doesn't honour ``response_format``.
    """
    raw = await llm.chat(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # be forgiving — strip code fences if any
        cleaned = raw.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        return json.loads(cleaned)


__all__ = [
    "LLMClient",
    "OpenAICompatibleClient",
    "AnthropicAdapter",
    "build_llm_client",
    "chat_json",
]
