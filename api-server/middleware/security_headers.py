"""
middleware/security_headers.py — HTTP Security Headers (Enterprise Grade)
=========================================================================
Ajoute les en-têtes de sécurité HTTP recommandés par OWASP pour une
application enterprise prête à la production.

Headers appliqués :
  - Strict-Transport-Security (HSTS)
  - X-Content-Type-Options
  - X-Frame-Options
  - X-XSS-Protection
  - Referrer-Policy
  - Permissions-Policy
  - Content-Security-Policy (CSP) — vrai nonce-based (V28: nonce injecté dans les directives)
  - Cache-Control (pour les endpoints API sensibles)
  - X-Permitted-Cross-Domain-Policies

V28 ENTERPRISE FIX (Audit P1-1) :
  - Le nonce est maintenant réellement injecté dans script-src et style-src.
  - 'unsafe-inline' retiré de style-src.
  - Un seul owner CSP : l'application. Nginx ne doit PAS émettre de CSP (voir nginx.tls.conf).
  - Le nonce est transmis via X-CSP-Nonce pour que le frontend l'injecte
    dans les balises <script> et <style> dynamiques.
  - Le nonce est également stocké dans request.state.csp_nonce pour les
    templates server-side éventuels.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Endpoints qui ne doivent pas être mis en cache (données sensibles)
SENSITIVE_PREFIXES = (
    "/api/v1/auth",
    "/api/v1/users",
    "/api/v1/billing",
    "/api/v1/admin",
    "/api/v1/security",
    "/api/v1/stores",
)


def _normalize_origin(value: str) -> str:
    raw = (value or "").strip().rstrip("/")
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _build_csp(nonce: str, extra_connect_src: str = "", *, secure_transport: bool = False) -> str:
    """
    Construit une CSP cohérente nonce-based.

    V28 FIX: le nonce est maintenant réellement utilisé dans script-src et style-src.
    'unsafe-inline' est retiré — les scripts/styles inline DOIVENT porter l'attribut
    nonce={nonce} pour être autorisés.
    """
    try:
        from config import settings as _s

        origins: list[str] = []
        for candidate in [getattr(_s, "SERVER_DOMAIN", ""), *getattr(_s, "CORS_ORIGINS", "").split(",")]:
            origin = _normalize_origin(candidate)
            if origin and origin not in origins:
                origins.append(origin)
    except Exception:
        origins = []

    connect_src = ["'self'", "https:", "wss:"]
    for origin in origins:
        if origin not in connect_src:
            connect_src.append(origin)
        if origin.startswith("http://"):
            ws_origin = "ws://" + origin[len("http://"):]
            if ws_origin not in connect_src:
                connect_src.append(ws_origin)
        elif origin.startswith("https://"):
            wss_origin = "wss://" + origin[len("https://"):]
            if wss_origin not in connect_src:
                connect_src.append(wss_origin)
    if extra_connect_src:
        connect_src.extend(part for part in extra_connect_src.split() if part)

    # V28: nonce injecté dans script-src ET style-src — unsafe-inline retiré des deux.
    # Le frontend doit injecter nonce="{nonce}" sur chaque balise <script> et <style> inline.
    # Le nonce est transmis via le header X-CSP-Nonce.
    directives = [
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        f"style-src 'self' 'nonce-{nonce}' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: blob: https:",
        f"connect-src {' '.join(connect_src)}",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ]
    if secure_transport:
        directives.append("upgrade-insecure-requests")
    return "; ".join(directives) + ";"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Injecte les en-têtes de sécurité HTTP sur toutes les réponses.
    Compatible avec les middlewares existants (TraceID, BodyLimit, CORS).

    V28 ENTERPRISE: génère un nonce CSP cryptographique par requête et l'injecte
    réellement dans les directives script-src et style-src de la CSP.
    Le nonce est disponible via :
      - response header X-CSP-Nonce (pour le frontend)
      - request.state.csp_nonce (pour les templates server-side)
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Générer un nonce cryptographique unique par requête (16 bytes = 128 bits)
        csp_nonce = secrets.token_urlsafe(16)
        # Exposer le nonce dans request.state pour les templates server-side
        request.state.csp_nonce = csp_nonce

        response = await call_next(request)

        # ── Transport Security ──────────────────────────────────────────
        secure_transport = request.url.scheme == "https"
        hsts_enabled = True
        try:
            from config import settings as _settings
            hsts_enabled = bool(getattr(_settings, "HSTS_ENABLED", True))
        except Exception:
            hsts_enabled = True
        if secure_transport and hsts_enabled:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )

        # ── Content Type ────────────────────────────────────────────────
        response.headers["X-Content-Type-Options"] = "nosniff"

        # ── Clickjacking ────────────────────────────────────────────────
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"

        # ── XSS Protection (legacy browsers) ────────────────────────────
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # ── Referrer Policy ─────────────────────────────────────────────
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # ── Permissions Policy ──────────────────────────────────────────
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=(), usb=(), "
            "magnetometer=(), gyroscope=(), accelerometer=(), autoplay=(), "
            "encrypted-media=(), midi=(), picture-in-picture=(), sync-xhr=(), "
            "fullscreen=(self), display-capture=()"
        )

        # Cross-Origin isolation hints
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Embedder-Policy", "require-corp")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")

        # ── Content Security Policy (vrai nonce-based — V28 ENTERPRISE) ─
        # Owner unique de la CSP : cette application.
        # Nginx ne doit PAS émettre de Content-Security-Policy (voir nginx.tls.conf).
        # Le nonce change à chaque requête — aucun cache navigateur ne peut le réutiliser.
        csp = _build_csp(csp_nonce, secure_transport=secure_transport)
        response.headers["Content-Security-Policy"] = csp
        response.headers["X-CSP-Nonce"] = csp_nonce

        # ── Cache Control (endpoints sensibles) ─────────────────────────
        path = request.url.path
        is_sensitive = any(path.startswith(p) for p in SENSITIVE_PREFIXES)
        if is_sensitive:
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, private, max-age=0"
            )
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        # ── Remove Server fingerprinting ────────────────────────────────
        for _hdr in ("server", "x-powered-by"):
            if _hdr in response.headers:
                del response.headers[_hdr]

        return response


__all__ = ["SecurityHeadersMiddleware"]
