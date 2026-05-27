"""HTTP routers."""

from __future__ import annotations

import importlib
import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Routers registered in build order. Missing modules are skipped (so the app
# can boot mid-refactor) — once a router lands, it is included automatically.
_ROUTER_MODULES: tuple[str, ...] = (
    "app.routers.checkin",
    "app.routers.hypotheses",
    "app.routers.chat",
    "app.routers.actions",
    "app.routers.profile",
    "app.routers.events",
    "app.routers.dashboard",
)


def register_routers(app: FastAPI) -> None:
    for path in _ROUTER_MODULES:
        try:
            module = importlib.import_module(path)
        except ModuleNotFoundError:
            logger.info("Router %s not yet present, skipping.", path)
            continue
        router = getattr(module, "router", None)
        if router is None:
            logger.warning("Router module %s missing `router` attribute.", path)
            continue
        app.include_router(router)
