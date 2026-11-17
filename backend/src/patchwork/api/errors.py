import logging
import sqlite3

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from patchwork.errors import PatchworkError
from patchwork.schemas.errors import ErrorDetail, ErrorResponse, ValidationIssue

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PatchworkError)
    async def application_error(request: Request, error: PatchworkError) -> JSONResponse:
        body = ErrorResponse(
            error=ErrorDetail(
                code=error.code,
                message=error.message,
                repository_id=error.repository_id,
                request_id=getattr(request.state, "request_id", None),
            )
        )
        return JSONResponse(status_code=error.status_code, content=body.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        details = [
            ValidationIssue(location=list(issue["loc"]), message=issue["msg"], type=issue["type"])
            for issue in error.errors()
        ]
        body = ErrorResponse(
            error=ErrorDetail(
                code="validation_error",
                message="Request validation failed.",
                request_id=getattr(request.state, "request_id", None),
                details=details,
            )
        )
        return JSONResponse(status_code=422, content=body.model_dump())

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        body = ErrorResponse(
            error=ErrorDetail(
                code=f"http_{error.status_code}",
                message=str(error.detail),
                request_id=getattr(request.state, "request_id", None),
            )
        )
        return JSONResponse(
            status_code=error.status_code, content=body.model_dump(), headers=error.headers
        )

    @app.exception_handler(sqlite3.Error)
    async def database_error(request: Request, error: sqlite3.Error) -> JSONResponse:
        logger.error("Database request failed", exc_info=error)
        body = ErrorResponse(
            error=ErrorDetail(
                code="storage_unavailable",
                message="Database storage is unavailable.",
                request_id=getattr(request.state, "request_id", None),
            )
        )
        return JSONResponse(status_code=503, content=body.model_dump())
