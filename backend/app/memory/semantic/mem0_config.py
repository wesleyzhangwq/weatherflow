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
    only when an embedding API key is configured.
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
            },
        },
    }
    if settings.embedding_api_key:
        config["embedder"] = {
            "provider": settings.embedding_provider,
            "config": {
                "model": settings.embedding_model,
                "api_key": settings.embedding_api_key,
            },
        }
    return config


__all__ = ["build_mem0_config"]
