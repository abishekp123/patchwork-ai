"""Application assembly. Run with `uvicorn patchwork.main:create_app --factory`."""

import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from patchwork import __version__
from patchwork.api.dashboard import router as dashboard_router
from patchwork.api.errors import register_error_handlers
from patchwork.api.health import router as health_router
from patchwork.api.investigations import router as investigations_router
from patchwork.api.observability import RequestContextMiddleware
from patchwork.api.patches import router as patches_router
from patchwork.api.repositories import router as repositories_router
from patchwork.api.verifications import router as verifications_router
from patchwork.config import Settings
from patchwork.database import initialize_database
from patchwork.runtime import application_owner, cleanup_orphans, reconcile


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        with application_owner(resolved_settings.database_path):
            initialize_database(resolved_settings.database_path)
            reconcile(resolved_settings.database_path)
            await asyncio.to_thread(cleanup_orphans, resolved_settings.database_path)
            try:
                yield
            finally:
                tasks = [
                    *app.state.verification_tasks.values(),
                    *app.state.investigation_tasks.values(),
                ]
                for task in tasks:
                    if not task.cancelling():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                try:
                    reconcile(resolved_settings.database_path, cancelled=True)
                except sqlite3.Error:
                    # Storage may have failed while serving. Do not mask graceful
                    # resource cleanup; startup will reconcile after storage is restored.
                    logging.getLogger(__name__).error(
                        "Shutdown state could not be persisted; restore SQLite before restart."
                    )

    app = FastAPI(title="Patchwork AI", version=__version__, lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.verification_tasks = {}
    app.state.investigation_tasks = {}
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router)
    app.include_router(dashboard_router, prefix="/api")
    app.include_router(investigations_router, prefix="/api")
    app.include_router(patches_router, prefix="/api")
    app.include_router(verifications_router, prefix="/api")
    app.include_router(repositories_router, prefix="/api")
    # Retain legacy unprefixed repository routes.
    app.include_router(repositories_router, include_in_schema=False)
    register_error_handlers(app)
    return app
