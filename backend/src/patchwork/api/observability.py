import logging
import re
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger("patchwork.request")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request.failed",
                extra={
                    "request_id": request_id,
                    "http_method": request.method,
                    "route": request.url.path[:256],
                },
            )
            raise
        route = request.scope.get("route")
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request.completed",
            extra={
                "request_id": request_id,
                "http_method": request.method,
                "route": getattr(route, "path", request.url.path)[:256],
                "status_code": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
            },
        )
        return response
