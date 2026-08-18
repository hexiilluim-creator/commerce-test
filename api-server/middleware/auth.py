"""
middleware/auth.py — Dépendances FastAPI d'authentification multi-tenant
========================================================================
"""

from __future__ import annotations

import hmac
import time

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from middleware.tenant import current_tenant_id
from models.database import Store, get_db

_HEALTH_DETAIL_BUCKET: dict[str, float] = {}
_HEALTH_DETAIL_WINDOW_SECONDS = 10.0


def _resolve_store_id(request: Request | None = None) -> int:
    sid = current_tenant_id.get()
    if sid is None and request is not None:
        sid = getattr(request.state, "store_id", None)
    if sid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tenant context missing",
        )
    return int(sid)


async def get_current_store_id(request: Request) -> int:
    return _resolve_store_id(request)


async def get_current_store(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Store:
    store_id = _resolve_store_id(request)

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found for current tenant",
        )
    return store


async def require_internal_health_token(
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
) -> None:
    from config import settings

    if not x_internal_token or not hmac.compare_digest(x_internal_token, settings.INTERNAL_HEALTH_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-Internal-Token missing or invalid",
        )


async def require_internal_health_rate_limit(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    bucket_key = f"{client}:{request.url.path}"
    now = time.monotonic()

    expired = [key for key, expiry in _HEALTH_DETAIL_BUCKET.items() if expiry <= now]
    for key in expired:
        _HEALTH_DETAIL_BUCKET.pop(key, None)

    expiry = _HEALTH_DETAIL_BUCKET.get(bucket_key)
    if expiry and expiry > now:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for internal health endpoint",
        )

    _HEALTH_DETAIL_BUCKET[bucket_key] = now + _HEALTH_DETAIL_WINDOW_SECONDS


__all__ = [
    "get_current_store",
    "get_current_store_id",
    "require_internal_health_rate_limit",
    "require_internal_health_token",
]
