"""api/v1/stores.py — Store self-introspection endpoint.

Added by CTO audit (v25.1) to back the legitimate frontend call
`GET /stores/me` made by the Settings page (OwnerAdminSection) which needs
the current store's owner_phone, slug, language, etc. — fields not exposed
by /auth/me (which is user-scoped).

Zero-regression: this is an ADDITIVE endpoint. No existing route is touched.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from middleware.tenant import current_tenant_id
from models.database import Store, get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stores", tags=["Stores"])


from api.v1._deps import get_store_id as _sid


@router.get("/me")
async def get_current_store(db: AsyncSession = Depends(get_db)):
    """Return the current authenticated store's profile (lightweight).

    Used by Settings.jsx → OwnerAdminSection to load `owner_phone` and other
    store-scoped fields not available via `/auth/me` (which is user-scoped).
    Never exposes encrypted credentials.
    """
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    return {
        "id": store.id,
        "name": store.name,
        "slug": store.slug,
        "language": store.language,
        "owner_phone": getattr(store, "owner_phone", None),
        "whatsapp_phone": store.whatsapp_phone,
        "logo_url": getattr(store, "logo_url", None),
        "support_email": getattr(store, "support_email", None),
        "is_active": store.is_active,
        "billing_status": getattr(store, "billing_status", None),
        "created_at": store.created_at.isoformat() if store.created_at else None,
    }
