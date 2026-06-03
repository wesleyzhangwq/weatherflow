"""OpenAI-compatible embedder for endpoints that reject the ``dimensions`` param.

mem0's built-in ``OpenAIEmbedding`` always sends ``dimensions=<n>`` to the
``/embeddings`` endpoint. That works for OpenAI's ``text-embedding-3-*`` (which
support configurable output dims) but **fails on SiliconFlow's BAAI/bge-m3**
(HTTP 400, code 20015) — bge-m3 has a fixed 1024-dim output and rejects the
parameter entirely.

This subclass overrides ``embed()`` to omit ``dimensions``. Everything else
(api_key / base_url wiring) is inherited. Registered with mem0's EmbedderFactory
under the ``siliconflow`` provider name by ``mem0_config.build_mem0_config``.
"""

from __future__ import annotations

from typing import Literal, Optional

from mem0.embeddings.openai import OpenAIEmbedding


class SiliconFlowEmbedding(OpenAIEmbedding):
    def embed(
        self, text, memory_action: Optional[Literal["add", "search", "update"]] = None
    ):
        text = text.replace("\n", " ")
        # No `dimensions` kwarg: bge-m3 is fixed at 1024 and 400s if it's sent.
        return self.client.embeddings.create(
            input=[text], model=self.config.model
        ).data[0].embedding


__all__ = ["SiliconFlowEmbedding"]
