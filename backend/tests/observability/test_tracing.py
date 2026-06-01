"""Tests for observability module (v2 Track 1C)."""

from __future__ import annotations

from app.observability.tracing import (
    get_trace_context,
    get_trace_id,
    set_conversation_id,
    set_trace_id,
    set_user_id,
)
from app.observability.structured_logging import (
    MetricsCollector,
    setup_structured_logging,
)


# ---------------------------------------------------------------------------
# Tests: OTel traceId (M1C.2)
# ---------------------------------------------------------------------------


def test_get_trace_id_generates_when_empty():
    """get_trace_id generates a new ID when none is set."""
    tid = get_trace_id()
    assert tid.startswith("trace_")
    assert len(tid) > 10


def test_set_and_get_trace_id():
    """Setting a trace ID persists it."""
    set_trace_id("trace_abc123")
    assert get_trace_id() == "trace_abc123"


def test_get_trace_context_includes_all_fields():
    """get_trace_context returns all context vars."""
    set_trace_id("trace_test")
    set_conversation_id("conv_test")
    set_user_id("user_test")
    ctx = get_trace_context()
    assert ctx["trace_id"] == "trace_test"
    assert ctx["conversation_id"] == "conv_test"
    assert ctx["user_id"] == "user_test"


# ---------------------------------------------------------------------------
# Tests: Metrics collector (M1C.3)
# ---------------------------------------------------------------------------


def test_metrics_increment():
    mc = MetricsCollector()
    mc.increment("tokens_used", 100)
    mc.increment("tokens_used", 50)
    assert mc.get_metrics()["counters"]["tokens_used"] == 150


def test_metrics_observe_histogram():
    mc = MetricsCollector()
    for v in [10, 20, 30, 40, 50]:
        mc.observe("latency_ms", v)
    m = mc.get_metrics()["histograms"]["latency_ms"]
    assert m["count"] == 5
    assert m["p50"] == 30
    assert m["min"] == 10
    assert m["max"] == 50


def test_metrics_gauge():
    mc = MetricsCollector()
    mc.gauge("active_users", 42)
    assert mc.get_metrics()["gauges"]["active_users"] == 42


def test_metrics_reset():
    mc = MetricsCollector()
    mc.increment("test", 1)
    mc.observe("test_hist", 1.0)
    mc.reset()
    m = mc.get_metrics()
    assert m["counters"] == {}
    assert m["histograms"] == {}


# ---------------------------------------------------------------------------
# Tests: Structured logging setup (M1C.3)
# ---------------------------------------------------------------------------


def test_setup_structured_logging_does_not_crash():
    """setup_structured_logging runs without error."""
    setup_structured_logging("DEBUG")
    import logging
    logger = logging.getLogger("test")
    logger.info("test message")
    # No assertion needed — just verify it doesn't crash
