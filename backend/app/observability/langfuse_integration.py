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
    if lf is None:
        yield _NoopSpan()
        return

    try:
        span = lf.trace(name=name, metadata=metadata or {})
        yield _LangfuseSpan(span)
    except Exception:
        logger.exception("Langfuse trace failed")
        yield _NoopSpan()


@contextmanager
def span(parent: Any, name: str, metadata: Optional[dict] = None):
    """Context manager for a child span within a trace."""
    lf = _get_langfuse()
    if lf is None:
        yield _NoopSpan()
        return

    try:
        child = parent.span(name=name, metadata=metadata or {}) if hasattr(parent, "span") else lf.trace(name=name)
        yield _LangfuseSpan(child)
    except Exception:
        logger.exception("Langfuse span failed")
        yield _NoopSpan()


class _LangfuseSpan:
    """Wrapper around a Langfuse trace/span."""

    def __init__(self, obj):
        self._obj = obj

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

    def update(self, **kwargs):
        pass

    def end(self):
        pass


def flush():
    """Flush pending Langfuse events."""
    lf = _get_langfuse()
    if lf:
        try:
            lf.flush()
        except Exception:
            pass


__all__ = ["trace", "span", "flush"]
