"""FastAPI app entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .admin import router as admin_router
from .config import get_settings
from .db import init_engine
from .router import BackendRegistry, probe_loop
from .routes.dashboard import router as dashboard_router
from .routes.dashboard_identity import router as dashboard_identity_router
from .routes.inference import router as inference_router
from .routes.status import router as status_router


log = logging.getLogger("student-lab")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_engine()
    registry = BackendRegistry(settings)
    app.state.registry = registry

    task = asyncio.create_task(probe_loop(registry, settings.health_probe_interval))
    log.info(
        "student-lab gateway up; backends=%s admin_email=%s",
        list(registry.names()),
        settings.admin_email,
    )
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="Student Lab Gateway",
        description="Authenticated, logged, queue-aware access to Jay's local LLM fleet.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(status_router)
    app.include_router(inference_router)
    app.include_router(admin_router)
    app.include_router(dashboard_identity_router)
    app.include_router(dashboard_router)
    return app


app = create_app()
