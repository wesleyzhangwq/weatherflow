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
    """Point mem0's ``openai`` embedder at our subclass that omits the
    ``dimensions`` param (SiliconFlow bge-m3 rejects it).

    We override the ``openai`` provider rather than registering a new name
    because mem0's ``EmbedderConfig`` pydantic validator only accepts a fixed
    allow-list of provider names. This process's only mem0 use is WeatherFlow's
    L2.5, so overriding ``openai`` here is safe. Idempotent; no-op without mem0.
    """
    try:
        from mem0.utils.factory import EmbedderFactory

        EmbedderFactory.provider_to_class["openai"] = (
            "app.memory.semantic.siliconflow_embedder.SiliconFlowEmbedding"
        )
    except Exception:
        pass


def build_mem0_config(settings: Settings) -> dict[str, Any]:
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
                "collection_name": settings.qdrant_collection,
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


__all__ = ["build_mem0_config"]
