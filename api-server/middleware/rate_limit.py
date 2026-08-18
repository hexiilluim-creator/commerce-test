"""
middleware/rate_limit.py — HTTP rate limiting (P2-C)
=====================================================
Uses slowapi (Starlette-compatible) backed by Redis.

Limits applied:
  - Auth endpoints: 10/minute per IP (brute-force protection)
  - WhatsApp webhook: 300/minute per IP (Meta sends bursts)
  - AI vision upload: 20/minute per tenant
  - General API: 120/minute per IP
"""

import functools
import inspect
import logging
import os
from typing import Any

from fastapi import HTTPException, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from config import settings
from middleware.tenant import current_tenant_id

logger = logging.getLogger(__name__)

# B1-FIX: Removed settings.ENV == "development" bypass.
# Using "memory://" storage when ENV=development caused each Uvicorn worker to have
# its own counter -> 8 workers × limit = 8× effective rate limit on staging.
# An attacker could brute-force /login 80 times/minute on a "protected" staging env.
#
# Now memory:// is ONLY used for pytest (PYTEST_CURRENT_TEST env set by pytest itself)
# or when explicitly opted-out via DISABLE_RATE_LIMIT=1 (documented ops escape hatch).
# All other environments (development, staging, production) use Redis — which is always
# available via docker-compose / K8s. If Redis is down, slowapi falls back gracefully.

# Use dedicated Redis DB for rate limiting when configured.
_redis_url = (
    getattr(settings, "REDIS_RATELIMIT_URL", "")
    or settings.REDIS_URL
    or "redis://localhost:6379"
)
storage_uri = _redis_url

# HIGH-7 FIX: SKIP_LIMITER=1 ne peut plus être utilisé en production.
# AVANT: la variable était honorée silencieusement dans tous les environnements.
# Un SKIP_LIMITER=1 accidentellement déployé en prod désactivait toute la protection
# brute-force sans alerte — une faute de configuration catastrophique.
# CORRIGÉ: en production/staging, SKIP_LIMITER=1 lève une erreur fatale au démarrage.
_env = os.getenv("ENV", "production").lower()
_is_test = (
    os.getenv("PYTEST_CURRENT_TEST")
    or os.getenv("ENV") == "test"
    or "pytest" in "".join(os.environ.keys()).lower()
)
_skip_limiter_requested = (
    _is_test
    or os.getenv("DISABLE_RATE_LIMIT") == "1"
    or os.getenv("SKIP_LIMITER") == "1"
)

if _skip_limiter_requested:
    if _env in ("production", "prod", "staging"):
        raise RuntimeError(
            "[SECURITY] SKIP_LIMITER=1 or DISABLE_RATE_LIMIT=1 cannot be used in "
            f"ENV={_env}. This would disable all rate limiting (brute-force, DDoS protection). "
            "If you need to bypass rate limiting for ops, use Redis FLUSHDB on the rate-limit "
            "Redis DB (REDIS_RATELIMIT_URL) instead."
        )
    storage_uri = "memory://"


def _test_key_func(request):
    import uuid
    return uuid.uuid4().hex


limiter = Limiter(
    key_func=_test_key_func if _is_test else get_remote_address,
    storage_uri=storage_uri,
    default_limits=["9999/minute"] if _is_test else ["120/minute"],
    in_memory_fallback_enabled=not _is_test,
    swallow_errors=True,
)


_tenant_rl_redis = None


def _extract_request(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Request | None:
    for value in kwargs.values():
        if isinstance(value, Request):
            return value
    for value in args:
        if isinstance(value, Request):
            return value
    return None


async def _get_tenant_rl_redis():
    global _tenant_rl_redis
    if _tenant_rl_redis is None:
        import redis.asyncio as aioredis

        _tenant_rl_redis = aioredis.Redis.from_url(
            _redis_url,
            decode_responses=True,
            max_connections=int(getattr(settings, "REDIS_MAX_CONNECTIONS", 10)),
            socket_timeout=float(getattr(settings, "REDIS_SOCKET_TIMEOUT", 5.0)),
            socket_connect_timeout=float(
                getattr(settings, "REDIS_SOCKET_CONNECT_TIMEOUT", 3.0)
            ),
        )
    return _tenant_rl_redis


def _resolve_store_id(request: Request) -> int | None:
    store_id = getattr(request.state, "store_id", None)
    if store_id is None:
        store_id = current_tenant_id.get()
    if store_id is None:
        raw = request.headers.get("X-Store-Id")
        if raw and raw.isdigit():
            store_id = int(raw)
    if store_id is None:
        return None
    try:
        return int(store_id)
    except (TypeError, ValueError):
        return None


async def _check_tenant_bucket(
    redis_client,
    *,
    key: str,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int]:
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.ttl(key)
    count, ttl = await pipe.execute()
    if ttl is None or ttl < 0:
        await redis_client.expire(key, window_seconds)
        ttl = window_seconds
    return int(count) <= int(limit), int(ttl)


async def _enforce_tenant_rate_limit(
    request: Request,
    *,
    limit: int,
    window_seconds: int,
    scope: str,
) -> None:
    if _is_test:
        return

    client_ip = request.client.host if request.client else "unknown"
    store_id = _resolve_store_id(request)
    ip_key = f"tenant_rl:{scope}:ip:{client_ip}"
    store_key = f"tenant_rl:{scope}:store:{store_id}" if store_id is not None else None

    try:
        redis_client = await _get_tenant_rl_redis()

        ip_allowed, ip_ttl = await _check_tenant_bucket(
            redis_client,
            key=ip_key,
            limit=limit,
            window_seconds=window_seconds,
        )

        store_allowed = True
        store_ttl = 0
        if store_key is not None:
            store_allowed, store_ttl = await _check_tenant_bucket(
                redis_client,
                key=store_key,
                limit=limit,
                window_seconds=window_seconds,
            )

        if not ip_allowed or not store_allowed:
            retry_after = max(ip_ttl, store_ttl, 1)
            logger.warning(
                "tenant_rate_limit_exceeded scope=%s store_id=%s ip=%s retry_after=%s",
                scope,
                store_id,
                client_ip,
                retry_after,
            )
            raise HTTPException(
                status_code=429,
                detail="Tenant rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.debug(
            "tenant_rate_limit fail-open scope=%s store_id=%s ip=%s error=%s",
            scope,
            store_id,
            client_ip,
            exc,
        )


def tenant_rate_limit(limit: int, window_seconds: int = 60, scope: str | None = None):
    """Decorator that rate-limits by tenant (store_id) and by client IP via Redis.

    The same limit is enforced on two buckets:
      - per IP address
      - per store_id (tenant context)

    If tenant context is unavailable, the decorator still enforces the IP bucket.
    Redis failures are fail-open to preserve API availability.
    """

    def decorator(func):
        rl_scope = scope or f"{func.__module__}.{func.__name__}"

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            request = _extract_request(args, kwargs)
            if request is None:
                raise RuntimeError(
                    "tenant_rate_limit requires a FastAPI Request parameter on the decorated endpoint"
                )

            await _enforce_tenant_rate_limit(
                request,
                limit=limit,
                window_seconds=window_seconds,
                scope=rl_scope,
            )

            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

        return wrapper

    return decorator


__all__ = [
    "limiter",
    "tenant_rate_limit",
    "RateLimitExceeded",
    "_rate_limit_exceeded_handler",
    "SlowAPIMiddleware",
]
