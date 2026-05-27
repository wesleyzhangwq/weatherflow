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
    logging.basicConfig(level=settings.log_level)
    logger.info("WeatherFlow starting up. db=%s", settings.db_path)

    from app.memory.event_log import init_db

    init_db(settings.db_path)
    app.state.settings = settings
    app.state.llm = build_llm_client(settings)

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
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await app.state.llm.aclose()
        logger.info("WeatherFlow shutting down.")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="WeatherFlow",
        description="A rhythm coach + daily cockpit for developers.",
        version="1.0.0",
        lifespan=lifespan,
    )

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
        return {
            "status": "ok",
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
        }

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "name": "WeatherFlow",
            "tagline": "Rhythm coach. Daily cockpit. Calendar + GitHub only.",
            "docs": "/docs",
        }

    return app


app = create_app()
