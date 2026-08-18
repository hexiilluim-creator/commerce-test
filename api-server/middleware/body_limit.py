"""
middleware/body_limit.py — HTTP request body size limit (E6 + E17)
===================================================================
Prevents OOM attacks via oversized uploads or webhook payloads.
FastAPI/Starlette has no built-in body size limit by default.

Limits:
  - /api/v1/ai/vision/upload : 5 MB  (image upload)
  - /api/v1/whatsapp/webhook : 512 KB (Meta webhook)
  - /api/v1/payments/webhook : 64 KB  (payment webhook)
  - All other endpoints      : 1 MB   (default)
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Limits in bytes
LIMITS = {
    "/api/v1/ai/vision/upload":    5 * 1024 * 1024,   # 5 MB
    "/api/v1/whatsapp/webhook":    512 * 1024,          # 512 KB
    "/api/v1/payments/webhook/":   64 * 1024,           # 64 KB  (prefix match)
}
DEFAULT_LIMIT = 1 * 1024 * 1024   # 1 MB


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Determine limit for this path
        limit = DEFAULT_LIMIT
        for pattern, size in LIMITS.items():
            if path == pattern or path.startswith(pattern):
                limit = size
                break

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > limit:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": "Request body too large",
                            "max_bytes": limit,
                            "received_bytes": int(content_length),
                        },
                    )
            except ValueError:
                pass  # malformed header — let it through, will fail naturally

        return await call_next(request)
