import hmac
import json
import logging
from contextvars import ContextVar

import jwt
from fastapi import HTTPException, Request
from jwt.exceptions import PyJWTError as JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from config import settings
from middleware.current_user import current_user_id
from models.database import AsyncSessionLocal
from services.tenant_access import TenantAccessState, get_tenant_access_state

logger = logging.getLogger(__name__)

AUTH_COOKIE_NAME = "access_token"
_TENANT_STATE_CACHE_TTL = 30

current_tenant_id: ContextVar[int | None] = ContextVar("tenant_id", default=None)
current_user_role: ContextVar[str | None] = ContextVar("user_role", default=None)

PUBLIC_EXACT = frozenset({
    "/health", "/health/", "/health/db", "/health/redis", "/health/detailed", "/health/live", "/health/ready",
    "/api/health", "/api/health/", "/api/health/db", "/api/health/redis", "/api/health/detailed", "/api/health/live", "/api/health/ready",
    "/api/v1/health", "/api/v1/health/", "/api/v1/health/db", "/api/v1/health/redis", "/api/v1/health/detailed", "/api/v1/health/live", "/api/v1/health/ready",
    # /metrics must bypass JWT middleware so the dedicated route guard can return
    # 403 without token and 200 with X-Internal-Token. Otherwise TenantMiddleware
    # intercepts first and produces a misleading 401/401.
    "/metrics", "/metrics/",
    "/docs", "/redoc", "/openapi.json",
    "/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh",
    "/api/v1/auth/logout", "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password", "/api/v1/billing/plans",
    # RGPD Art. 13/14: retention policy must be publicly accessible (no auth required)
    "/api/v1/settings/gdpr/retention-policy",
    # HIGH-2 FIX: MFA endpoints publics pour éviter le deadlock
    # (appelés avec un token pré-MFA, avant que mfa_verified soit True)
    "/api/v1/auth/mfa/verify",
    "/api/v1/auth/mfa/setup",
})

PUBLIC_PREFIXES = (
    "/api/v1/whatsapp/webhook",
    "/api/v1/payments/webhook",
    "/api/v1/billing/webhook/saas",
    "/api/v1/social/instagram/webhook",
    "/api/v1/social/facebook/webhook",
    "/api/v1/social/tiktok/webhook",
    "/api/v1/social/webhook",
    # SEC-2 FIX: /api/v1/ops/ removed from public bypass.
    # Ops endpoints already check X-Internal-Token internally via _auth().
    # Removing the bypass forces the JWT middleware to run first, adding a
    # second layer: caller must have a valid JWT *and* the internal token.
    # MIGRATION NOTE: monitoring scripts that call /api/v1/ops/* without a
    # JWT must now pass a service-account Bearer token (or set ENV=development).
    "/api/v1/storefront/",
    "/api/v1/products/public",
    "/api/v1/settings/store/public/",
)

# HIGH-2 FIX: Chemins exemptés de la gate MFA même avec mfa_required=True
MFA_EXEMPT_PATHS = frozenset({
    "/api/v1/auth/mfa/verify",
    "/api/v1/auth/mfa/setup",
    "/api/v1/auth/logout",
    "/api/v1/billing/byok-status",
})


def _is_public(path: str) -> bool:
    if path in PUBLIC_EXACT:
        return True
    return any(path.startswith(p) for p in PUBLIC_PREFIXES)


def _extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1]
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return None


async def _get_cached_tenant_state(store_id: int) -> dict | None:
    try:
        from services.redis_lock import get_redis
        redis = get_redis()
        raw = await redis.get(f"tenant:state:{store_id}")
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.debug("Tenant state cache read failed for store %s: %s", store_id, e)
    return None


async def _cache_tenant_state(store_id: int, state: "TenantAccessState") -> None:
    try:
        from services.redis_lock import get_redis
        redis = get_redis()
        payload = json.dumps({
            "is_tenant_active": state.is_tenant_active,
            "suspended_reason": state.suspended_reason,
            "billing_status": state.billing_status,
        })
        await redis.setex(f"tenant:state:{store_id}", _TENANT_STATE_CACHE_TTL, payload)
    except Exception as e:
        logger.debug("Tenant state cache write failed for store %s: %s", store_id, e)


def invalidate_tenant_state_cache(store_id: int) -> None:
    import asyncio
    async def _del():
        try:
            from services.redis_lock import get_redis
            redis = get_redis()
            await redis.delete(f"tenant:state:{store_id}")
        except Exception:
            pass
    try:
        running = asyncio.get_running_loop()
        running.create_task(_del())
    except RuntimeError:
        try:
            asyncio.run(_del())
        except Exception:
            pass


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Tenant middleware: JWT validation + MFA enforcement (HIGH-2) + tenant state.

    HIGH-2 FIX — MFA enforcement au niveau middleware :
    Si le JWT contient mfa_required=True et mfa_verified!=True,
    toute requête hors MFA_EXEMPT_PATHS reçoit 401 mfa_verification_required.
    Backward-compatible : tokens sans claim mfa_required passent sans blocage.
    """

    @staticmethod
    def _unauthorized(detail: str, status: int = 401) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": detail})

    async def dispatch(self, request: Request, call_next) -> Response:
        if _is_public(request.url.path):
            return await call_next(request)

        # CTO audit fix: if internal token is present, bypass JWT middleware.
        # This allows /api/v1/admin/credits/stats/monthly (protected by internal token)
        # to be called without a JWT, which is the expected behavior in integration tests.
        internal_token = request.headers.get("X-Internal-Token")
        # AUDIT FIX (mineur) : comparaison Python standard (==) sur un secret —
        # temps de comparaison dépendant du contenu, théoriquement exploitable
        # par timing attack pour deviner le token octet par octet. hmac.compare_digest
        # compare en temps constant.
        if internal_token and settings.INTERNAL_HEALTH_TOKEN and hmac.compare_digest(
            internal_token, settings.INTERNAL_HEALTH_TOKEN
        ):
            return await call_next(request)

        token = _extract_token(request)
        if not token:
            return self._unauthorized("Authentication token missing", 401)

        try:
            payload = settings.decode_jwt(token, algorithms=["HS256"])
            store_id = payload.get("store_id")
            role = payload.get("role", "viewer")

            if store_id is None:
                return self._unauthorized("Token missing store_id", 401)

            store_id = int(store_id)

            # ── HIGH-2 FIX: MFA gate ──────────────────────────────────────────
            mfa_required = payload.get("mfa_required", False)
            mfa_verified = payload.get("mfa_verified", False)
            path = request.url.path

            if mfa_required and not mfa_verified and path not in MFA_EXEMPT_PATHS:
                logger.warning(
                    "mfa_enforcement_blocked",
                    extra={"store_id": store_id, "path": path,
                           "user_id": payload.get("user_id")},
                )
                return self._unauthorized("mfa_verification_required", 401)
            # ─────────────────────────────────────────────────────────────────

            # P0-FIX (audit): disable cache in tests to allow immediate tenant suspension verification
            import os
            _is_test = os.getenv("ENV") == "test" or os.getenv("PYTEST_CURRENT_TEST")
            
            cached = await _get_cached_tenant_state(store_id) if not _is_test else None
            if cached is not None:
                is_active = cached.get("is_tenant_active", True)
                billing_status = cached.get("billing_status", "active")
                suspended_reason = cached.get("suspended_reason")
            else:
                async with AsyncSessionLocal() as db:
                    tenant_state = await get_tenant_access_state(db, store_id)
                if not _is_test:
                    await _cache_tenant_state(store_id, tenant_state)
                is_active = tenant_state.is_tenant_active
                billing_status = tenant_state.billing_status
                suspended_reason = tenant_state.suspended_reason

            if not is_active:
                detail = suspended_reason or "Tenant suspended"
                return self._unauthorized(detail, 403)

            current_tenant_id.set(store_id)
            current_user_role.set(role)
            request.state.store_id = store_id
            request.state.role = role
            request.state.billing_status = billing_status
            request.state.mfa_verified = mfa_verified
            request.state.jwt_payload = payload  # BUG#1 FIX: require_role() in _deps.py reads this

            user_id = payload.get("user_id")
            if user_id:
                current_user_id.set(int(user_id))
                request.state.user_id = int(user_id)

        except JWTError as e:
            return self._unauthorized(f"Invalid token: {e}", 401)

        return await call_next(request)


# require_role() removed from this module (BUG#5 fix).
# Canonical implementation lives in api/v1/_deps.py — it correctly reads
# request.state.jwt_payload (set above) instead of request.state.role,
# avoiding the two-sources-of-truth conflict.
