"""
middleware/input_validation.py — Input Validation & Sanitization (OWASP A03)
=============================================================================
Première ligne de défense contre les injections et les payloads malveillants.

Protections :
  - Détection de patterns d'injection SQL
  - Détection de patterns XSS dans les query strings
  - Validation des en-têtes HTTP suspects
  - Blocage des User-Agents de scanners connus
  - Validation du Content-Type pour les requêtes POST/PUT/PATCH
  - Détection de path traversal

Note : Cette couche est complémentaire à la validation Pydantic des modèles.
       Elle opère au niveau transport, avant que FastAPI ne parse le body.
"""
from __future__ import annotations

import re

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger("input_validation")

# ── Patterns d'injection SQL ────────────────────────────────────────────────
SQL_INJECTION_PATTERNS = re.compile(
    r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|EXECUTE|UNION|"
    r"TRUNCATE|DECLARE|CAST|CONVERT|CHAR|NCHAR|VARCHAR|NVARCHAR|"
    r"xp_|sp_|0x[0-9a-fA-F]+)\b|"
    r"(--|;|/\*|\*/|@@|@[a-zA-Z]+|WAITFOR\s+DELAY|BENCHMARK\s*\(|"
    r"SLEEP\s*\(|pg_sleep\s*\())",
    re.IGNORECASE,
)

# ── Patterns XSS ────────────────────────────────────────────────────────────
XSS_PATTERNS = re.compile(
    r"(<script[\s\S]*?>[\s\S]*?</script>|"
    r"javascript\s*:|"
    r"\bon\w+\s*=|"
    r"<\s*iframe|<\s*object|<\s*embed|<\s*applet|"
    r"expression\s*\(|"
    r"vbscript\s*:|"
    r"data\s*:\s*text/html)",
    re.IGNORECASE,
)

# ── Path Traversal ──────────────────────────────────────────────────────────
PATH_TRAVERSAL_PATTERNS = re.compile(
    r"(\.\./|\.\.\\|%2e%2e%2f|%2e%2e/|\.\./|\.\.%2f|%252e%252e%252f)",
    re.IGNORECASE,
)

# ── User-Agents de scanners/bots malveillants ────────────────────────────────
MALICIOUS_UA_PATTERNS = re.compile(
    r"(sqlmap|nikto|nmap|masscan|zgrab|nuclei|"
    r"dirbuster|gobuster|wfuzz|hydra|medusa|"
    r"burpsuite|owasp|acunetix|nessus|openvas|"
    r"w3af|skipfish|webscarab|paros)",
    re.IGNORECASE,
)

# Endpoints exemptés de la validation stricte (webhooks avec signatures)
VALIDATION_EXEMPT_PATHS = (
    "/api/v1/whatsapp/webhook",
    "/api/v1/payments/webhook",
    "/api/v1/social/instagram/webhook",
    "/api/v1/social/facebook/webhook",
    "/api/v1/social/tiktok/webhook",
    "/health",
    "/metrics",
)

# Content-Types acceptés pour les requêtes avec body
ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/x-www-form-urlencoded",
    "multipart/form-data",
    "text/plain",
}


def _check_query_string(query: str) -> str | None:
    """Retourne le type de menace détecté, ou None si propre."""
    if SQL_INJECTION_PATTERNS.search(query):
        return "sql_injection"
    if XSS_PATTERNS.search(query):
        return "xss"
    if PATH_TRAVERSAL_PATTERNS.search(query):
        return "path_traversal"
    return None


def _check_path(path: str) -> str | None:
    """Vérifie le chemin URL pour les attaques de traversal."""
    if PATH_TRAVERSAL_PATTERNS.search(path):
        return "path_traversal"
    # Null byte injection
    if "\x00" in path or "%00" in path:
        return "null_byte_injection"
    return None


class InputValidationMiddleware(BaseHTTPMiddleware):
    """
    Middleware de validation des entrées HTTP.
    Bloque les requêtes contenant des patterns d'attaque connus.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method

        # Endpoints exemptés
        if any(path.startswith(p) for p in VALIDATION_EXEMPT_PATHS):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        # ── 1. Vérification du chemin URL ────────────────────────────────
        path_threat = _check_path(path)
        if path_threat:
            logger.warning(
                "input_threat_detected",
                threat_type=path_threat,
                location="path",
                path=path,
                client_ip=client_ip,
            )
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid request path"},
            )

        # ── 2. Vérification de la query string ───────────────────────────
        query_string = request.url.query
        if query_string:
            query_threat = _check_query_string(query_string)
            if query_threat:
                logger.warning(
                    "input_threat_detected",
                    threat_type=query_threat,
                    location="query_string",
                    path=path,
                    client_ip=client_ip,
                )
                return JSONResponse(
                    status_code=400,
                    content={"error": "Invalid query parameters"},
                )

        # ── 3. Vérification du User-Agent ────────────────────────────────
        user_agent = request.headers.get("user-agent", "")
        if user_agent and MALICIOUS_UA_PATTERNS.search(user_agent):
            logger.warning(
                "malicious_user_agent_blocked",
                user_agent=user_agent[:200],
                path=path,
                client_ip=client_ip,
            )
            return JSONResponse(
                status_code=403,
                content={"error": "Forbidden"},
            )

        # ── 4. Validation du Content-Type (requêtes avec body) ───────────
        if method in {"POST", "PUT", "PATCH"}:
            content_type = request.headers.get("content-type", "")
            # Extraire le type sans les paramètres (ex: charset)
            base_content_type = content_type.split(";")[0].strip().lower()
            if base_content_type and base_content_type not in ALLOWED_CONTENT_TYPES:
                logger.warning(
                    "invalid_content_type",
                    content_type=content_type,
                    path=path,
                    client_ip=client_ip,
                )
                return JSONResponse(
                    status_code=415,
                    content={
                        "error": "Unsupported Media Type",
                        "allowed": list(ALLOWED_CONTENT_TYPES),
                    },
                )

        # ── 5. Vérification des en-têtes suspects ────────────────────────
        # Détection d'injections dans les en-têtes personnalisés
        for header_name in ["x-forwarded-for", "x-real-ip", "x-forwarded-host"]:
            header_val = request.headers.get(header_name, "")
            if header_val and (
                SQL_INJECTION_PATTERNS.search(header_val)
                or XSS_PATTERNS.search(header_val)
            ):
                logger.warning(
                    "header_injection_detected",
                    header=header_name,
                    path=path,
                    client_ip=client_ip,
                )
                return JSONResponse(
                    status_code=400,
                    content={"error": "Invalid request headers"},
                )

        return await call_next(request)


__all__ = ["InputValidationMiddleware"]
