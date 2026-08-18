"""
middleware/trace_id.py — Request correlation ID (E18)
======================================================
Generates a unique X-Request-ID for every request.
Propagated through:
  - HTTP response headers (visible to clients)
  - structlog context (all log lines carry trace_id)
  - Celery task payloads (correlates async work to origin request)
"""

import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ContextVar — readable anywhere in the request/task lifecycle
current_trace_id: ContextVar[str] = ContextVar("trace_id", default="")


class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Accept incoming trace ID (e.g. from API gateway) or generate new one
        trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        current_trace_id.set(trace_id)
        request.state.trace_id = trace_id

        # Bind to structlog for automatic inclusion in all log lines
        structlog.contextvars.bind_contextvars(trace_id=trace_id)

        response = await call_next(request)

        # Return trace_id so callers can correlate logs
        response.headers["X-Request-ID"] = trace_id

        # Clear structlog context for this request
        structlog.contextvars.clear_contextvars()

        return response


def get_trace_id() -> str:
    """Get current request trace_id from anywhere in the call stack."""
    return current_trace_id.get() or ""
