"""
middleware/audit_log.py — Audit Logging Enterprise (OWASP A09)
==============================================================
HIGH-10 FIX: Chaque entrée d'audit inclut un champ `entry_hmac`
calculé avec HMAC-SHA256 sur le contenu JSON canonique de l'entrée,
signé avec JWT_SECRET_KEY.

Vérification offline :
  import hmac, hashlib, json
  entry_copy = {k: v for k, v in entry.items() if k != "entry_hmac"}
  expected = hmac.new(SECRET.encode(),
      json.dumps(entry_copy, sort_keys=True).encode(), hashlib.sha256).hexdigest()
  assert expected == entry["entry_hmac"]
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config import settings

logger = structlog.get_logger("audit")

AUDIT_PREFIXES = (
    "/api/v1/auth", "/api/v1/admin", "/api/v1/super-admin",
    "/api/v1/security", "/api/v1/billing", "/api/v1/stores",
    "/api/v1/users", "/api/v1/payments",
)
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SECURITY_STATUSES = {401, 403, 429}


def _should_audit(path: str, method: str, status: int) -> bool:
    if status in SECURITY_STATUSES:
        return True
    if any(path.startswith(p) for p in AUDIT_PREFIXES):
        return True
    if method in WRITE_METHODS and path.startswith("/api/"):
        return True
    return False


def _mask_sensitive(headers: dict) -> dict:
    masked = {}
    sensitive_keys = {"authorization", "x-api-key", "cookie", "set-cookie"}
    for k, v in headers.items():
        masked[k] = "***REDACTED***" if k.lower() in sensitive_keys else v
    return masked


def _sign_entry(entry: dict, secret: str) -> str:
    """
    HIGH-10 FIX: HMAC-SHA256 sur la représentation JSON canonique de l'entrée.
    Couvre tous les champs — toute modification invalide le HMAC.
    """
    payload = json.dumps(entry, sort_keys=True, default=str)
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class AuditLogMiddleware(BaseHTTPMiddleware):
    """
    Middleware d'audit logging enterprise avec tamper-proofing HMAC (HIGH-10).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.monotonic()
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        trace_id = getattr(request.state, "trace_id", "")
        store_id = getattr(request.state, "store_id", None)

        response = await call_next(request)

        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
        status_code = response.status_code
        path = request.url.path
        method = request.method

        if _should_audit(path, method, status_code):
            if status_code in SECURITY_STATUSES:
                log_fn = logger.warning
                event_type = "security_event"
            elif status_code >= 500:
                log_fn = logger.error
                event_type = "server_error"
            elif method in WRITE_METHODS:
                log_fn = logger.info
                event_type = "data_mutation"
            else:
                log_fn = logger.info
                event_type = "sensitive_access"

            # HIGH-10 FIX: Construire l'entrée, puis la signer
            entry: dict = {
                "event": event_type,
                "timestamp": time.time(),
                "trace_id": trace_id,
                "store_id": store_id,
                "client_ip": client_ip,
                "method": method,
                "path": path,
                "query": str(request.url.query) if request.url.query else None,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "user_agent": user_agent[:200] if user_agent else None,
                "is_auth_failure": status_code == 401,
                "is_forbidden": status_code == 403,
                "is_rate_limited": status_code == 429,
            }

            try:
                entry["entry_hmac"] = _sign_entry(entry, settings.JWT_SECRET_KEY)
            except Exception as _sign_err:
                entry["entry_hmac"] = "SIGNING_FAILED"
                entry["signing_error"] = str(_sign_err)[:100]

            log_fn(**entry)

        return response


__all__ = ["AuditLogMiddleware"]
