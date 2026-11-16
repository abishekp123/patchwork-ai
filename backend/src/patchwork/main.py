"""Application assembly. Run with `uvicorn patchwork.main:create_app --factory`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from patchwork import __version__
from patchwork.api.errors import register_error_handlers
from patchwork.api.health import router as health_router
from patchwork.api.investigations import router as investigations_router
from patchwork.api.repositories import router as repositories_router
from patchwork.config import Settings
from patchwork.database import initialize_database


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        initialize_database(resolved_settings.database_path)
        yield

    app = FastAPI(title="Patchwork AI", version=__version__, lifespan=lifespan)
    app.state.settings = resolved_settings
    app.include_router(health_router)
    app.include_router(investigations_router, prefix="/api")
    app.include_router(repositories_router, prefix="/api")
    # Preserve the existing Vite proxy, which removes /api before forwarding.
    app.include_router(repositories_router, include_in_schema=False)
    register_error_handlers(app)
    return app
