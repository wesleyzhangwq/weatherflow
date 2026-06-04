"""Langfuse integration — trace LLM calls and graph nodes.

Per weatherflow-architecture-v2.md §15, one agent run = one trace,
graph nodes = spans, tool calls = spans. Records token/cost/model.

Falls back to no-op when langfuse is not installed or keys are missing.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Optional

logger = logging.getLogger(__name__)

_langfuse_client = None
_initialized = False


def _get_langfuse():
    """Lazy-init Langfuse client. Returns None if unavailable."""
    global _langfuse_client, _initialized

    if _initialized:
        return _langfuse_client

    _initialized = True
    try:
        from langfuse import Langfuse
        from app.config import get_settings

        settings = get_settings()
        if not settings.langfuse_public_key or not settings.langfuse_secret_key:
            logger.debug("Langfuse keys not set, tracing disabled")
            return None

        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("Langfuse initialized (host=%s)", settings.langfuse_host)
        return _langfuse_client

    except ImportError:
        logger.debug("langfuse not installed, tracing disabled")
        return None
    except Exception:
        logger.exception("Failed to initialize Langfuse")
        return None


@contextmanager
def trace(name: str, metadata: Optional[dict] = None):
    """Context manager for a Langfuse trace span.

    Usage:
        with trace("chat_request", {"user_id": "default"}) as t:
            # do work
            t.update(output={"tokens": 100})
    """
    lf = _get_langfuse()
    span_obj: Any = None
    if lf is not None:
        try:
            span_obj = _LangfuseSpan(lf.trace(name=name, metadata=metadata or {}))
        except Exception:
            logger.exception("Langfuse trace init failed")
    # Yield exactly once; let exceptions from the with-body propagate cleanly.
    yield span_obj if span_obj is not None else _NoopSpan()


@contextmanager
def span(parent: Any, name: str, metadata: Optional[dict] = None):
    """Context manager for a child span within a trace."""
    lf = _get_langfuse()
    span_obj: Any = None
    if lf is not None:
        try:
            child = parent.span(name=name, metadata=metadata or {}) if hasattr(parent, "span") else lf.trace(name=name)
            span_obj = _LangfuseSpan(child)
        except Exception:
            logger.exception("Langfuse span init failed")
    yield span_obj if span_obj is not None else _NoopSpan()


class _LangfuseSpan:
    """Wrapper around a Langfuse trace/span (supports child span + generation)."""

    def __init__(self, obj):
        self._obj = obj

    def span(self, name: str, metadata: Optional[dict] = None) -> "Any":
        try:
            return _LangfuseSpan(self._obj.span(name=name, metadata=metadata or {}))
        except Exception:
            return _NoopSpan()

    def generation(self, *, name: str, model: Any = None, usage: Optional[dict] = None,
                   metadata: Optional[dict] = None) -> None:
        try:
            self._obj.generation(
                name=name, model=model, usage=usage or {}, metadata=metadata or {}
            )
        except Exception:
            pass

    def update(self, **kwargs):
        try:
            self._obj.update(**kwargs)
        except Exception:
            pass

    def end(self):
        try:
            self._obj.end()
        except Exception:
            pass


class _NoopSpan:
    """No-op span when Langfuse is unavailable."""

    def span(self, *args, **kwargs):
        return self

    def generation(self, *args, **kwargs):
        return None

    def update(self, **kwargs):
        pass

    def end(self):
        pass


# ---------------------------------------------------------------------------
# Trace-tree helpers (ADR-004 D3): one trace per run, nodes = spans, LLM = gen.
# ---------------------------------------------------------------------------


def start_trace(name: str, metadata: Optional[dict] = None) -> Any:
    """Create a root trace handle (live or no-op). The caller binds it via
    tracing.run_context(trace=...) so nodes attach spans under it."""
    lf = _get_langfuse()
    if lf is None:
        return _NoopSpan()
    try:
        return _LangfuseSpan(lf.trace(name=name, metadata=metadata or {}))
    except Exception:
        logger.exception("Langfuse start_trace failed")
        return _NoopSpan()


@contextmanager
def observe_node(name: str, metadata: Optional[dict] = None):
    """Open a child span (under the current trace/span) for a graph node body,
    and bind it as the current span so nested LLM generations attach to it."""
    from app.observability.tracing import current_span, get_current_span, get_current_trace

    parent = get_current_span() or get_current_trace()
    child = parent.span(name=name, metadata=metadata or {}) if parent is not None else _NoopSpan()
    with current_span(child):
        try:
            yield child
        finally:
            child.end()


def _map_usage(usage: dict) -> dict:
    if not usage:
        return {}
    return {
        "input": usage.get("prompt_tokens"),
        "output": usage.get("completion_tokens"),
        "total": usage.get("total_tokens"),
    }


def record_generation(
    *, model: Any = None, usage: Optional[dict] = None, latency_ms: Optional[float] = None,
    name: str = "llm.chat",
) -> None:
    """Record one LLM call as a generation under the current span/trace. If no
    run is bound, fall back to a standalone trace so the call stays observable."""
    from app.observability.tracing import get_current_span, get_current_trace

    parent = get_current_span() or get_current_trace()
    md = {"latency_ms": round(latency_ms, 1)} if latency_ms is not None else {}
    if parent is not None:
        parent.generation(name=name, model=model, usage=_map_usage(usage or {}), metadata=md)
    else:
        with trace(name, {"model": model}) as t:
            t.update(output={"usage": usage or {}, **md})


def flush():
    """Flush pending Langfuse events."""
    lf = _get_langfuse()
    if lf:
        try:
            lf.flush()
        except Exception:
            pass


__all__ = ["trace", "span", "start_trace", "observe_node", "record_generation", "flush"]
