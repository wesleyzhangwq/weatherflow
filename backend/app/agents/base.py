"""Common base for all SubAgents."""

from __future__ import annotations

from app.core.llm import LLMClient


class BaseAgent:
    """Tiny base class so agents share a constructor signature.

    Agents should remain lightweight; we keep this minimal on purpose.
    """

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm


__all__ = ["BaseAgent"]
