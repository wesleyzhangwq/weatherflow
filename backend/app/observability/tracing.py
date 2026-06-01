"""OpenTelemetry traceId propagation.

Per weatherflow-architecture-v2.md §15.2, generates traceId at HTTP entry
and propagates via contextvars across async boundaries.

Falls back to generating a simple UUID traceId when OTel is not installed.
"""

from __future__ import annotations

import contextvars
import logging
import uuid

logger = logging.getLogger(__name__)

# Context variable for trace ID propagation across async boundaries
_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)
_conversation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "conversation_id", default=""
)
_user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "user_id", default=""
)

_otel_initialized = False


def init_otel() -> None:
    """Initialize OpenTelemetry if available. Idempotent."""
    global _otel_initialized
    if _otel_initialized:
        return
    _otel_initialized = True

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, BatchSpanProcessor
        from app.config import get_settings

        settings = get_settings()

        provider = TracerProvider()

        if settings.otel_exporter == "console":
            processor = BatchSpanProcessor(ConsoleSpanExporter())
        else:
            # OTLP exporter (Jaeger, etc.)
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                processor = BatchSpanProcessor(OTLPSpanExporter())
            except ImportError:
                processor = BatchSpanProcessor(ConsoleSpanExporter())

        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        logger.info("OpenTelemetry initialized (exporter=%s)", settings.otel_exporter)

    except ImportError:
        logger.debug("opentelemetry not installed, using simple traceId")


def get_trace_id() -> str:
    """Get the current trace ID. Generates one if not set."""
    tid = _trace_id_var.get("")
    if not tid:
        tid = f"trace_{uuid.uuid4().hex[:16]}"
        _trace_id_var.set(tid)
    return tid


def set_trace_id(trace_id: str) -> None:
    """Set the current trace ID (called at HTTP entry)."""
    _trace_id_var.set(trace_id)


def get_conversation_id() -> str:
    return _conversation_id_var.get("")


def set_conversation_id(cid: str) -> None:
    _conversation_id_var.set(cid)


def get_user_id() -> str:
    return _user_id_var.get("")


def set_user_id(uid: str) -> None:
    _user_id_var.set(uid)


def get_trace_context() -> dict:
    """Get all trace context as a dict (for log enrichment)."""
    return {
        "trace_id": get_trace_id(),
        "conversation_id": get_conversation_id(),
        "user_id": get_user_id(),
    }


__all__ = [
    "init_otel",
    "get_trace_id",
    "set_trace_id",
    "get_conversation_id",
    "set_conversation_id",
    "get_user_id",
    "set_user_id",
    "get_trace_context",
]
