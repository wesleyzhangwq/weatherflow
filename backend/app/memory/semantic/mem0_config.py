"""Shared mem0 configuration builder for the L2.5 semantic memory layer.

Both the projector (write) and recall (read) paths need an identical mem0
config pointed at the same Qdrant instance + embedder. Centralising it here
avoids drift and replaces fragile hand-rolled URL string slicing with
``urllib.parse`` (G16).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.config import Settings


def _register_custom_embedders() -> None:
    """Point mem0's ``openai`` provider at our subclasses:
      - embedder → SiliconFlowEmbedding (omits the ``dimensions`` param that
        bge-m3 rejects);
      - llm → MiniMaxLLM (strips MiniMax-M3 ``<think>`` blocks so infer=True
        fact-extraction can JSON-parse the response — ADR-006).

    We override the ``openai`` provider in place rather than registering a new
    name (mem0's pydantic validators only accept a fixed allow-list). This
    process's only mem0 use is WeatherFlow, so overriding is safe. Idempotent;
    no-op without mem0.
    """
    try:
        from mem0.utils.factory import EmbedderFactory, LlmFactory

        EmbedderFactory.provider_to_class["openai"] = (
            "app.memory.semantic.siliconflow_embedder.SiliconFlowEmbedding"
        )
        # LlmFactory entries are (class_path, config_class) tuples — keep the
        # config class, swap only the LLM class.
        _, llm_cfg = LlmFactory.provider_to_class["openai"]
        LlmFactory.provider_to_class["openai"] = (
            "app.memory.semantic.minimax_llm.MiniMaxLLM",
            llm_cfg,
        )
    except Exception:
        pass


def build_mem0_config(
    settings: Settings, *, collection: str | None = None
) -> dict[str, Any]:
    """Build a mem0 ``Memory.from_config`` dict from app settings.

    Parses ``QDRANT_URL`` robustly (scheme/host/port) and wires the embedder
    only when an embedding API key is configured. The embedder's ``base_url``
    and ``embedding_dims`` are threaded through so an OpenAI-compatible gateway
    (e.g. Alibaba dashscope) is actually used instead of api.openai.com, and the
    Qdrant collection is created at the matching vector size.

    The ``llm`` section points at the project's chat gateway (MiniMax). The
    projector uses ``mem0.add(..., infer=False)`` so this LLM is never *called*
    for extraction — but mem0 constructs the LLM client eagerly in
    ``Memory.__init__`` and raises if it has no api_key, so it must be wired
    with valid creds regardless.
    """
    _register_custom_embedders()

    parsed = urlparse(settings.qdrant_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6333

    config: dict[str, Any] = {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "host": host,
                "port": port,
                "collection_name": collection or settings.qdrant_collection,
                "embedding_model_dims": settings.embedding_dims,
            },
        },
        "llm": {
            "provider": "openai",
            "config": {
                "model": settings.chat_model,
                "api_key": settings.openai_api_key,
                "openai_base_url": settings.openai_base_url,
            },
        },
    }
    if settings.embedding_api_key:
        embedder_config: dict[str, Any] = {
            "model": settings.embedding_model,
            "api_key": settings.embedding_api_key,
            "embedding_dims": settings.embedding_dims,
        }
        if settings.embedding_base_url:
            embedder_config["openai_base_url"] = settings.embedding_base_url
        config["embedder"] = {
            "provider": settings.embedding_provider,
            "config": embedder_config,
        }
    return config


_MEMORY_CACHE: dict[str, Any] = {}


def get_memory(settings: Settings, *, collection: str | None = None) -> Any:
    """Process-wide cached mem0 ``Memory``, one per (qdrant url, collection).

    ``Memory.from_config`` eagerly constructs the Qdrant client, embedder and
    LLM client — rebuilding all of that on every recall added avoidable
    latency to every chat turn and every check-in. The cache key includes the
    Qdrant URL so tests (or env changes) pointing at a different instance get
    a fresh client instead of a stale one.
    """
    from mem0 import Memory

    key = f"{settings.qdrant_url}|{collection or settings.qdrant_collection}"
    m = _MEMORY_CACHE.get(key)
    if m is None:
        m = Memory.from_config(build_mem0_config(settings, collection=collection))
        _MEMORY_CACHE[key] = m
    return m


__all__ = ["build_mem0_config", "get_memory"]
