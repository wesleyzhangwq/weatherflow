"""Per-request run-context plumbing (ADR-004 P1).

Live objects (trace/span/llm) live in contextvars, never in AgentState. These
tests pin the set/get/reset semantics and the get_request_llm() bound-vs-fresh
behaviour that P2/P3 build on.
"""

from __future__ import annotations

import pytest

from app.core.llm import OpenAICompatibleClient, get_request_llm
from app.observability import tracing


def test_defaults_are_none():
    assert tracing.get_current_trace() is None
    assert tracing.get_current_span() is None
    assert tracing.get_request_llm() is None


def test_run_context_binds_and_resets():
    sentinel_trace = object()
    sentinel_llm = object()

    assert tracing.get_current_trace() is None
    with tracing.run_context(trace=sentinel_trace, llm=sentinel_llm):
        assert tracing.get_current_trace() is sentinel_trace
        assert tracing.get_request_llm() is sentinel_llm
    # resets on exit
    assert tracing.get_current_trace() is None
    assert tracing.get_request_llm() is None


def test_current_span_nesting():
    outer, inner = object(), object()
    with tracing.current_span(outer):
        assert tracing.get_current_span() is outer
        with tracing.current_span(inner):
            assert tracing.get_current_span() is inner
        assert tracing.get_current_span() is outer
    assert tracing.get_current_span() is None


def test_get_request_llm_returns_bound_client():
    bound = object()
    with tracing.run_context(llm=bound):
        assert get_request_llm() is bound


@pytest.mark.asyncio
async def test_get_request_llm_falls_back_when_unbound():
    # No run bound → builds a fresh real client (must be closed by the caller).
    client = get_request_llm()
    assert isinstance(client, OpenAICompatibleClient)
    await client.aclose()
