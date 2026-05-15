"""FastAPI entry point for WeatherFlow."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.llm import build_llm_client
from app.core.orchestrator import Orchestrator
from app.core.scheduler import build_scheduler
from app.memory.store import init_db
from app.sensors.sweep_runner import run_sensor_sweep
from app.routers import checkin, feedback, mcp, memory, reflection, sensors, state

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    logger.info("WeatherFlow starting up. db=%s", settings.db_path)

    init_db(settings.db_path)
    app.state.settings = settings
    app.state.llm = build_llm_client(settings)

    async def _evening_job() -> None:
        try:
            logger.info("Evening reflection job firing.")
            await Orchestrator(app.state.llm).daily_loop()
        except Exception:
            logger.exception("Evening reflection job failed.")

    async def _weekly_job() -> None:
        try:
            logger.info("Weekly review job firing.")
            await Orchestrator(app.state.llm).weekly_loop()
        except Exception:
            logger.exception("Weekly review job failed.")

    async def _sensor_sweep_job() -> None:
        if not get_settings().sensor_sweep_enabled:
            return
        try:
            logger.info("Sensor sweep job firing.")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: run_sensor_sweep(settings=get_settings(), dry_run=False),
            )
        except Exception:
            logger.exception("Sensor sweep job failed.")

    scheduler = build_scheduler(
        settings,
        daily_job=_evening_job,
        weekly_job=_weekly_job,
        sensor_sweep_job=_sensor_sweep_job,
    )
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
    app = FastAPI(
        title="WeatherFlow",
        description="A long-term growth companion agent.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(checkin.router)
    app.include_router(feedback.router)
    app.include_router(reflection.router)
    app.include_router(state.router)
    app.include_router(sensors.router)
    app.include_router(memory.router)
    app.include_router(mcp.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/meta/status", tags=["meta"])
    def meta_status() -> dict:
        settings = get_settings()
        scheduler = getattr(app.state, "scheduler", None)
        data_dir = Path(settings.data_dir).expanduser()
        memory_dir = Path(settings.resolved_memory_markdown_dir).expanduser()
        return {
            "status": "ok",
            "data_dir": str(data_dir),
            "db_path": settings.db_path,
            "db_exists": Path(settings.db_path).exists(),
            "memory_markdown_dir": str(memory_dir),
            "memory_markdown_exists": memory_dir.exists(),
            "scheduler": {
                "enabled": settings.scheduler_enabled,
                "running": bool(getattr(scheduler, "running", False)),
                "jobs": [job.id for job in scheduler.get_jobs()] if scheduler else [],
            },
            "llm": {
                "chat_configured": bool(settings.openai_api_key.strip()),
                "embedding_configured": bool(
                    (settings.embedding_api_key or settings.openai_api_key).strip()
                ),
                "chat_model": settings.chat_model,
                "embedding_model": settings.embedding_model,
                "embedding_dim": settings.embedding_dim,
            },
            "long_term_memory": {
                "backend": "qdrant" if settings.qdrant_url.strip() else "sqlite",
                "qdrant_configured": bool(settings.qdrant_url.strip()),
                "collection": settings.qdrant_collection,
            },
            "cors_allowed_origins": settings.cors_origins,
        }

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "name": "WeatherFlow",
            "tagline": "An AI companion for long-term human growth.",
            "docs": "/docs",
        }

    return app


app = create_app()
