import logging
import sqlite3

from fastapi import APIRouter, Request, Response, status

from patchwork import __version__
from patchwork.config import Settings
from patchwork.database import check_database
from patchwork.schemas.health import HealthChecks, HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
def health(request: Request, response: Response) -> HealthResponse:
    """Report API and basic SQLite connectivity; never expose internal errors."""
    settings: Settings = request.app.state.settings
    response.headers["Cache-Control"] = "no-store"
    try:
        check_database(settings.database_path)
    except sqlite3.Error:
        logger.exception("SQLite health check failed")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="degraded", version=__version__, checks=HealthChecks(database="error")
        )
    return HealthResponse(status="ok", version=__version__, checks=HealthChecks(database="ok"))
