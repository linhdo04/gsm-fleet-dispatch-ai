from __future__ import annotations

import time
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from fleet_dispatch.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

logger = structlog.get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        request.state.request_id = request_id
        started_at = time.perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = time.perf_counter() - started_at
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            HTTP_REQUESTS.labels(request.method, path, status_code).inc()
            HTTP_REQUEST_DURATION.labels(request.method, path).observe(duration)
            logger.info(
                "http_request_completed",
                method=request.method,
                path=path,
                status_code=status_code,
                duration_ms=round(duration * 1000, 2),
                client_ip=request.client.host if request.client else None,
            )
            structlog.contextvars.clear_contextvars()
