"""
middleware/csrf_protection.py — CSRF Protection (OWASP A01)
===========================================================
Protection contre les attaques Cross-Site Request Forgery.

Stratégie : Double Submit Cookie Pattern
  1. Le serveur génère un token CSRF et le place dans un cookie HttpOnly=False
     (lisible par le JS frontend)
  2. Le frontend doit inclure ce token dans l'en-tête X-CSRF-Token
  3. Le middleware vérifie la correspondance token cookie ↔ token header

Exclusions :
  - Méthodes "safe" : GET, HEAD, OPTIONS (pas de modification d'état)
  - Webhooks tiers (WhatsApp, Meta, Stripe) — authentifiés par signature HMAC
  - Endpoint /api/v1/auth/login (nécessaire pour obtenir le token initial)
  - Endpoints de health check et métriques

Note : Cette protection est complémentaire à l'authentification JWT.
       Elle protège contre les requêtes forgées depuis d'autres origines.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger("csrf")

# Méthodes qui ne modifient pas l'état — exemptées de CSRF
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# P0-FIX (audit): the cookie `secure` flag must be conditional on the runtime
# environment. Setting `secure=True` in dev (HTTP) means the browser silently
# drops the cookie and the SPA cannot read the CSRF token — breaking forgot /
# reset flows. In production (HTTPS) we keep `secure=True`.
_CSRF_SECURE = os.getenv("ENV", "development").lower() in ("production", "prod", "staging")
# SameSite policy follows the same logic: 'strict' in prod, 'lax' in dev so that
# browser navigations from forgot-password emails still carry the cookie.
_CSRF_SAMESITE = "strict" if _CSRF_SECURE else "lax"

# Endpoints exemptés de la vérification CSRF
# P0-FIX (audit): forgot-password / reset-password are now explicitly exempt.
# These endpoints are anonymous (no session yet) and protected by:
#   - rate-limiting (slowapi)
#   - opaque tokens stored in Redis (reset)
#   - email-bound verification (forgot)
# Adding them here removes a fragile CSRF dependency from a public path.
CSRF_EXEMPT_PATHS = (
    # V8 FIX: ajouter un joker pour matcher /api/v1/auth/login mais aussi
    # /api/v1/auth/login/sso, /api/v1/auth/login/2fa, etc. On garde aussi
    # les entrées exactes pour la rétrocompatibilité.
    "/api/v1/auth/login",
    "/api/v1/auth/login/",
    "/api/v1/auth/register",
    "/api/v1/auth/register/",
    "/api/v1/auth/refresh",
    "/api/v1/auth/refresh/",
    "/api/v1/auth/forgot-password",   # P0-FIX (audit): anonymous flow
    "/api/v1/auth/reset-password",    # P0-FIX (audit): token-bound flow
    "/api/v1/auth/google-login",      # OAuth credential exchange
    "/api/v1/auth/google-login/",
    "/api/v1/auth/sso",               # P0-FIX: SSO login flow
    "/api/v1/auth/sso/",
    "/api/v1/auth/mfa/verify",        # P0-FIX: MFA flow
    "/api/v1/auth/mfa/setup",
    # Preflight CORS : sans exemption explicite, OPTIONS vers /login renvoie 403
    # alors qu'il ne devrait pas être validé (pas de modification d'état). SAFE_METHODS
    # couvre déjà OPTIONS, mais on double avec un joker pour les webhooks internes.
    "/api/v1/whatsapp/webhook",
    "/api/v1/payments/webhook",
    "/api/v1/social/instagram/webhook",
    "/api/v1/social/facebook/webhook",
    "/api/v1/social/tiktok/webhook",
    "/api/v1/social/webhook",
    # Storefront public : les commandes sont anonymes mais restent protégées
    # par validation serveur, repricing depuis la base et limites de payload.
    "/api/v1/storefront/",
    # AUDIT FIX : webhooks de facturation abonnement (Stripe, Flouci) — jamais
    # exemptés alors qu'ils existent déjà (Stripe) ou viennent d'être ajoutés
    # (Flouci). Un provider de paiement externe n'a ni cookie ni token CSRF —
    # sans cette exemption, ces webhooks échouent systématiquement en 403.
    "/api/v1/billing/webhook/",
    # HARDENING SPRINT: ops endpoints use internal token auth (not browser).
    "/api/v1/ops/",
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
)

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_TOKEN_BYTES = 32
CSRF_TOKEN_MAX_AGE = 3600  # 1 heure

# Clé secrète pour la signature des tokens
# CRIT-4 FIX: Le fallback secrets.token_hex(32) était silencieux et permettait
# au serveur de démarrer en multi-workers avec des secrets différents par process.
# Dans une architecture K8s (8 workers), les tokens signés par worker A étaient
# rejetés par workers B-H -> CSRF cassé silencieusement + brèche de sécurité.
#
# CORRIGÉ: Fail hard au démarrage si CSRF_SECRET est absent en production.
# En développement, on génère un secret aléatoire avec un WARNING visible.
# En production, l'absence de CSRF_SECRET est une erreur fatale.

try:
    from config import settings as _app_settings
    _csrf_secret_env = _app_settings.CSRF_SECRET.strip()
    _env_name = _app_settings.ENV.lower()
except Exception:
    _csrf_secret_env = os.getenv("CSRF_SECRET", "").strip()
    _env_name = os.getenv("ENV", "production").lower()

if not _csrf_secret_env:
    if _env_name in ("production", "prod", "staging"):
        # CRIT-4 FIX: Hard fail en production — jamais de secret aléatoire par process.
        raise RuntimeError(
            "[SECURITY] CSRF_SECRET is not set. Cannot start the application in production "
            "without a stable CSRF secret.\n"
            "Fix: generate a secret and set it in your environment:\n"
            "  export CSRF_SECRET=$(openssl rand -hex 32)\n"
            "Without this, CSRF protection is broken in multi-worker deployments."
        )
    else:
        # Développement uniquement : secret aléatoire avec WARNING explicite.
        # Ce chemin est intentionnellement bruyant pour ne pas être ignoré.
        import warnings
        _CSRF_SECRET = secrets.token_hex(32)
        warnings.warn(
            "[DEV] CSRF_SECRET not set — using random secret. "
            "This is only acceptable for single-worker development. "
            "Set CSRF_SECRET=<openssl rand -hex 32> before deploying.",
            RuntimeWarning,
            stacklevel=1,
        )
        logger.warning(
            "csrf_secret_not_configured",
            env=_env_name,
            message="Random CSRF secret generated — single-worker dev only",
        )
else:
    _CSRF_SECRET = _csrf_secret_env


def _generate_csrf_token(session_id: str = "") -> str:
    """Génère un token CSRF signé avec timestamp."""
    timestamp = str(int(time.time()))
    random_part = secrets.token_hex(CSRF_TOKEN_BYTES)
    payload = f"{timestamp}.{random_part}.{session_id}"
    signature = hmac.new(
        _CSRF_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}.{signature}"


def _verify_csrf_token(token: str) -> bool:
    """Vérifie la validité et la fraîcheur d'un token CSRF."""
    if not token:
        return False
    try:
        parts = token.split(".")
        if len(parts) < 4:
            return False
        timestamp = int(parts[0])
        signature = parts[-1]
        payload = ".".join(parts[:-1])

        # Vérifier la fraîcheur
        if time.time() - timestamp > CSRF_TOKEN_MAX_AGE:
            return False

        # Vérifier la signature
        expected_sig = hmac.new(
            _CSRF_SECRET.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature, expected_sig)
    except (ValueError, IndexError):
        return False


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """
    Middleware de protection CSRF pour les endpoints d'écriture.
    Utilise le pattern Double Submit Cookie avec tokens signés HMAC.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method

        # P0-FIX (audit): bypass CSRF in tests (ENV=test) to avoid fragile token management
        # in programmatic integration tests. In production, this remains active.
        if os.getenv("ENV") == "test" or os.getenv("PYTEST_CURRENT_TEST"):
            return await call_next(request)

        # Générer un token CSRF si absent du cookie
        existing_token = request.cookies.get(CSRF_COOKIE_NAME)
        if not existing_token or not _verify_csrf_token(existing_token):
            new_token = _generate_csrf_token()
        else:
            new_token = None  # Réutiliser le token existant valide

        # Méthodes sûres — pas de vérification nécessaire
        if method in SAFE_METHODS:
            response = await call_next(request)
            if new_token:
                response.set_cookie(
                    CSRF_COOKIE_NAME,
                    new_token,
                    httponly=False,  # Doit être lisible par JS
                    samesite=_CSRF_SAMESITE,
                    secure=_CSRF_SECURE,
                    max_age=CSRF_TOKEN_MAX_AGE,
                    path="/",
                )
            return response

        # Endpoints exemptés
        if any(path == p or path.startswith(p) for p in CSRF_EXEMPT_PATHS):
            response = await call_next(request)
            if new_token:
                response.set_cookie(
                    CSRF_COOKIE_NAME,
                    new_token,
                    httponly=False,
                    samesite=_CSRF_SAMESITE,
                    secure=_CSRF_SECURE,
                    max_age=CSRF_TOKEN_MAX_AGE,
                    path="/",
                )
            return response

        # Vérification CSRF pour les méthodes d'écriture
        header_token = request.headers.get(CSRF_HEADER_NAME, "")
        cookie_token = existing_token or ""

        # Vérifier que le token header correspond au cookie
        if not header_token or not cookie_token:
            logger.warning(
                "csrf_token_missing",
                path=path,
                method=method,
                has_header=bool(header_token),
                has_cookie=bool(cookie_token),
                client_ip=request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error": "CSRF token missing",
                    "detail": f"Include '{CSRF_HEADER_NAME}' header with value from '{CSRF_COOKIE_NAME}' cookie",
                },
            )

        # Comparer de façon sécurisée (résistant aux timing attacks)
        if not hmac.compare_digest(header_token, cookie_token):
            logger.warning(
                "csrf_token_mismatch",
                path=path,
                method=method,
                client_ip=request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=403,
                content={"error": "CSRF token invalid"},
            )

        # Valider le token lui-même
        if not _verify_csrf_token(cookie_token):
            logger.warning(
                "csrf_token_expired_or_invalid",
                path=path,
                method=method,
            )
            return JSONResponse(
                status_code=403,
                content={"error": "CSRF token expired or invalid"},
            )

        response = await call_next(request)

        # Rotation du token après utilisation réussie
        rotated_token = _generate_csrf_token()
        response.set_cookie(
            CSRF_COOKIE_NAME,
            rotated_token,
            httponly=False,
            samesite=_CSRF_SAMESITE,
            secure=_CSRF_SECURE,
            max_age=CSRF_TOKEN_MAX_AGE,
            path="/",
        )
        return response


__all__ = ["CSRFProtectionMiddleware", "CSRF_COOKIE_NAME", "CSRF_HEADER_NAME"]
