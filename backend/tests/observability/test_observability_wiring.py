"""Observability wiring — metrics, /metrics endpoint, Langfuse + recall degradation.

These cover the integration points (G4–G7, G11/G12) without requiring a real
Langfuse or mem0 instance: token/latency metrics flow into the collector, the
endpoint exposes them, the Langfuse trace context manager is a safe no-op, and
the semantic recall node degrades to an empty list.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.llm import _record_llm_metrics
from app.main import create_app
from app.observability.langfuse_integration import trace
from app.observability.structured_logging import metrics


def test_record_llm_metrics_populates_collector():
    metrics.reset()
    _record_llm_metrics({"total_tokens": 123}, latency_ms=42.0)

    out = metrics.get_metrics()
    assert out["counters"].get("llm.calls") == 1
    assert out["histograms"]["llm.latency_ms"]["count"] == 1
    assert out["histograms"]["llm.tokens"]["max"] == 123.0


def test_metrics_endpoint_exposes_collector():
    metrics.reset()
    _record_llm_metrics({"total_tokens": 10}, latency_ms=5.0)

    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/meta/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"counters", "gauges", "histograms"}
    assert body["counters"].get("llm.calls") == 1


def test_langfuse_trace_is_safe_noop_without_keys():
    # Span methods must be safe to call; body exceptions must propagate cleanly
    # (regression guard for the old double-yield bug).
    with trace("unit-test", {"k": "v"}) as span:
        span.update(output={"tokens": 1})
        span.end()

    with pytest.raises(ValueError):
        with trace("unit-test") as span:
            raise ValueError("boom")


def test_observe_node_binds_span_and_record_generation_is_safe():
    """ADR-004 D3: observe_node binds a current span; record_generation records
    a generation under it (no-op without keys) and resets cleanly. Outside a
    run it falls back to a standalone trace — both paths must never raise."""
    from app.observability.langfuse_integration import observe_node, record_generation
    from app.observability.tracing import get_current_span

    assert get_current_span() is None
    with observe_node("plan"):
        assert get_current_span() is not None  # bound (noop span when langfuse off)
        record_generation(model="m", usage={"total_tokens": 5}, latency_ms=1.0)
    assert get_current_span() is None  # reset on exit

    # Outside any run → standalone trace fallback, still must not raise.
    record_generation(model="m", usage={}, latency_ms=1.0)


@pytest.mark.asyncio
async def test_recall_memory_node_degrades_to_empty(monkeypatch):
    import app.memory.semantic.recall as recall_mod

    async def boom(*a, **k):
        raise RuntimeError("mem0/qdrant down")

    monkeypatch.setattr(recall_mod, "recall_relevant", boom)
    from app.agents.graph.chat_graph import recall_memory_node

    out = await recall_memory_node({"bundle_text": "overload last week", "user_id": "default"})
    assert out == {"semantic_memories": []}


@pytest.mark.asyncio
async def test_semantic_recall_returns_empty_without_mem0(monkeypatch):
    # Force the backend-unavailable path deterministically — mem0 may be
    # installed and Qdrant up in the dev env, so don't rely on ambient state.
    import mem0

    def boom(*a, **k):
        raise RuntimeError("mem0 unavailable")

    monkeypatch.setattr(mem0.Memory, "from_config", boom)
    from app.memory.semantic.recall import recall_relevant

    assert await recall_relevant("anything", user_id="default") == []
