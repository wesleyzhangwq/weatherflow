"""Structured JSON logging with trace context enrichment.

Per weatherflow-architecture-v2.md §15.3, logs carry trace_id, conversation_id,
and user_id. Also provides a simple metrics collector.
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from typing import Any


class StructuredFormatter(logging.Formatter):
    """JSON log formatter that enriches records with trace context."""

    def format(self, record: logging.LogRecord) -> str:
        from app.observability.tracing import get_trace_context

        ctx = get_trace_context()

        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": ctx.get("trace_id", ""),
            "conversation_id": ctx.get("conversation_id", ""),
            "user_id": ctx.get("user_id", ""),
        }

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


def setup_structured_logging(level: str = "INFO") -> None:
    """Configure root logger with structured JSON output."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# Simple metrics collector (M1C.3)
# ---------------------------------------------------------------------------


class MetricsCollector:
    """In-memory metrics collector for key business metrics.

    Tracks: token usage, latency P50/P95, hypothesis confidence,
    semantic recall hit rate, proposal confirmation rate.
    """

    def __init__(self):
        self._counters: dict[str, int] = defaultdict(int)
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._gauges: dict[str, float] = {}

    def increment(self, name: str, value: int = 1) -> None:
        self._counters[name] += value

    def observe(self, name: str, value: float) -> None:
        self._histograms[name].append(value)
        # Keep last 1000 values to avoid memory growth
        if len(self._histograms[name]) > 1000:
            self._histograms[name] = self._histograms[name][-1000:]

    def gauge(self, name: str, value: float) -> None:
        self._gauges[name] = value

    def get_metrics(self) -> dict[str, Any]:
        """Export all metrics as a dict."""
        result: dict[str, Any] = {"counters": dict(self._counters), "gauges": dict(self._gauges)}

        histograms = {}
        for name, values in self._histograms.items():
            if not values:
                continue
            sorted_v = sorted(values)
            n = len(sorted_v)
            histograms[name] = {
                "count": n,
                "p50": sorted_v[n // 2],
                "p95": sorted_v[int(n * 0.95)],
                "min": sorted_v[0],
                "max": sorted_v[-1],
                "mean": sum(sorted_v) / n,
            }
        result["histograms"] = histograms
        return result

    def reset(self) -> None:
        self._counters.clear()
        self._histograms.clear()
        self._gauges.clear()


# Global metrics instance
metrics = MetricsCollector()


__all__ = ["setup_structured_logging", "metrics", "MetricsCollector"]
