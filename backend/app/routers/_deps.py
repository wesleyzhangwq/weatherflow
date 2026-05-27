"""FastAPI dependency injectors."""

from __future__ import annotations

from fastapi import Request

from app.core.llm import LLMClient


def get_llm(request: Request) -> LLMClient:
    return request.app.state.llm
