"""Shared FastAPI dependencies for routers."""

from __future__ import annotations

from fastapi import Request

from app.core.llm import LLMClient
from app.core.orchestrator import Orchestrator


def get_llm(request: Request) -> LLMClient:
    return request.app.state.llm


def get_orchestrator(request: Request) -> Orchestrator:
    return Orchestrator(request.app.state.llm)


__all__ = ["get_llm", "get_orchestrator"]
