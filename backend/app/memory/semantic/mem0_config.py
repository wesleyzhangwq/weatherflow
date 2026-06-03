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


def build_mem0_config(settings: Settings) -> dict[str, Any]:
    """Build a mem0 ``Memory.from_config`` dict from app settings.

    Parses ``QDRANT_URL`` robustly (scheme/host/port) and wires the embedder
    only when an embedding API key is configured. The embedder's ``base_url``
    and ``embedding_dims`` are threaded through so an OpenAI-compatible gateway
    (e.g. Alibaba dashscope) is actually used instead of api.openai.com, and the
    Qdrant collection is created at the matching vector size.

    No ``llm`` section is configured on purpose: the projector calls
    ``mem0.add(..., infer=False)`` to store our curated, source-linked projection
    verbatim, so mem0 never needs an LLM (and never re-generalizes — that is
    profile.md / L3's job, per ADR-004 D5).
    """
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
