"""FastAPI entry point for WeatherFlow."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.llm import build_llm_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Environment hardening — must run before any HTTP client / mem0 import:
    # 1) mem0's PostHog telemetry phones home and retry-storms the logs when a
    #    proxy blocks it; a local-first app should not phone home by default.
    # 2) NO_PROXY_HOSTS routes the listed API hosts around a MITM-ing local
    #    proxy (see config.py) — httpx/openai clients read proxy env at build.
    import os

    os.environ.setdefault("MEM0_TELEMETRY", "False")
    if settings.no_proxy_hosts.strip():
        for var in ("NO_PROXY", "no_proxy"):
            existing = os.environ.get(var, "")
            merged = [h.strip() for h in existing.split(",") if h.strip()]
            for host in settings.no_proxy_hosts.split(","):
                if (h := host.strip()) and h not in merged:
                    merged.append(h)
            os.environ[var] = ",".join(merged)
        logger.info("NO_PROXY extended with: %s", settings.no_proxy_hosts)

    # v2 (M1C.3): JSON logs enriched with trace_id / conversation_id / user_id.
    from app.observability.structured_logging import setup_structured_logging

    setup_structured_logging(settings.log_level)
    logger.info("WeatherFlow starting up. db=%s", settings.db_path)

    from app.memory.event_log import init_db

    init_db(settings.db_path)
    app.state.settings = settings
    app.state.llm = build_llm_client(settings)

    # v2 (ADR-004 D2): compile the chat graph once with a SQLite checkpointer so
    # write Proposals can pause (interrupt) and resume across requests. The
    # saver holds an aiosqlite connection for the app lifetime.
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from app.agents.graph.chat_graph import build_chat_graph

    saver_cm = AsyncSqliteSaver.from_conn_string(settings.graph_checkpoints_path)
    app.state.graph_saver_cm = saver_cm
    saver = await saver_cm.__aenter__()
    app.state.chat_graph = build_chat_graph(checkpointer=saver)
    logger.info("Chat graph compiled with checkpointer at %s", settings.graph_checkpoints_path)

    # v2 (M1C.2): Initialize OpenTelemetry + instrument FastAPI when available.
    try:
        from app.observability.tracing import init_otel
        init_otel()
    except ImportError:
        pass
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        pass
    except Exception:
        logger.debug("FastAPI OTel instrumentation skipped", exc_info=True)

    # Overhaul phase 2: the MCP server is the single source of truth for tool
    # schemas — discover the registry over the protocol; any failure keeps the
    # static fallback so startup never blocks on a subprocess.
    if settings.wf_mcp_discovery_enabled:
        from app.mcp_client.tool_registry import init_registry_via_discovery

        try:
            import asyncio as _asyncio

            ok = await _asyncio.wait_for(init_registry_via_discovery(), timeout=30)
            logger.info(
                "MCP tool discovery: %s",
                "registry built from protocol" if ok else "fell back to static registry",
            )
        except Exception:  # noqa: BLE001
            logger.warning("MCP tool discovery errored; static registry in use", exc_info=True)

    scheduler = None
    try:
        from app.core.scheduler import build_scheduler

        scheduler = build_scheduler(settings)
    except ImportError:
        logger.info("Scheduler not yet implemented; skipping.")
    app.state.scheduler = scheduler
    if scheduler is not None:
        scheduler.start()

    try:
        yield
    finally:
        from app.mcp_client.pool import shutdown_pool

        try:
            await shutdown_pool()
        except Exception:  # noqa: BLE001
            logger.debug("MCP session pool shutdown failed", exc_info=True)
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        cm = getattr(app.state, "graph_saver_cm", None)
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                logger.debug("graph saver close failed", exc_info=True)
        await app.state.llm.aclose()
        logger.info("WeatherFlow shutting down.")


class TraceContextMiddleware:
    """Pure-ASGI middleware: assign a trace_id per request (M1C.2).

    Reads an incoming ``X-Trace-Id`` / ``X-Request-Id`` header if present,
    otherwise generates one. The id is stored in a contextvar so it threads
    through router → orchestrator → graph nodes → tools → llm and into the
    structured logs, and is echoed back on the response.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from app.observability.tracing import get_trace_id, set_trace_id

        headers = {k.lower(): v for k, v in (scope.get("headers") or [])}
        incoming = headers.get(b"x-trace-id") or headers.get(b"x-request-id")
        if incoming:
            set_trace_id(incoming.decode("latin-1"))
        trace_id = get_trace_id()  # generates + stores one if not set

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                msg_headers = list(message.get("headers") or [])
                msg_headers.append((b"x-trace-id", trace_id.encode("latin-1")))
                message["headers"] = msg_headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="WeatherFlow",
        description="A rhythm coach + daily cockpit for developers.",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(TraceContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers wired up per phase
    from app.routers import register_routers

    register_routers(app)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/meta/status", tags=["meta"])
    def meta_status() -> dict:
        s = get_settings()
        sched = getattr(app.state, "scheduler", None)

        # v2 service health checks
        qdrant_ok = False
        try:
            import httpx
            resp = httpx.get(f"{s.qdrant_url}/healthz", timeout=2.0)
            qdrant_ok = resp.status_code == 200
        except Exception:
            pass

        langfuse_ok = bool(s.langfuse_public_key and s.langfuse_secret_key)

        return {
            "status": "ok",
            "version": "2.0.0",
            "data_dir": str(Path(s.data_dir).expanduser()),
            "db_path": s.db_path,
            "db_exists": Path(s.db_path).exists(),
            "profile_dir": s.resolved_memory_markdown_dir,
            "scheduler": {
                "enabled": s.scheduler_enabled,
                "running": bool(getattr(sched, "running", False)),
                "jobs": [j.id for j in sched.get_jobs()] if sched else [],
            },
            "llm": {
                "chat_model": s.chat_model,
                "configured": bool(s.openai_api_key.strip()),
            },
            "v2_services": {
                "qdrant": {"url": s.qdrant_url, "healthy": qdrant_ok},
                "langfuse": {"configured": langfuse_ok, "host": s.langfuse_host},
                "semantic_memory": {"enabled": qdrant_ok},
                "proactivity": {"enabled": s.proactivity_enabled},
            },
        }

    @app.get("/api/meta/metrics", tags=["meta"])
    def meta_metrics() -> dict:
        """Expose in-process business metrics (M1C.3): token usage, stage
        latency P50/P95, counters. Backed by the global MetricsCollector."""
        from app.observability.structured_logging import metrics

        return metrics.get_metrics()

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "name": "WeatherFlow",
            "tagline": "Rhythm coach. Daily cockpit. Calendar + GitHub only.",
            "docs": "/docs",
        }

    return app


app = create_app()
