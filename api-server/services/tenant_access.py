"""services/tenant_access.py — Tenant access state resolution.

Provides TenantAccessState dataclass and get_tenant_access_state async function
used by TenantMiddleware to check if a tenant (Store) is active and their billing status.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class TenantAccessState:
    """Snapshot of a tenant's access rights."""
    is_tenant_active: bool
    billing_status: str
    suspended_reason: str | None = None


async def get_tenant_access_state(db: AsyncSession, store_id: int) -> TenantAccessState:
    """Fetch the current access state for a store from the database.

    Returns a TenantAccessState that fails closed when the store is missing
    or the database cannot be queried.
    """
    try:
        from models.database import Store
        result = await db.execute(select(Store).where(Store.id == store_id))
        store = result.scalar_one_or_none()

        if store is None:
            logger.warning("get_tenant_access_state: store %s not found", store_id)
            return TenantAccessState(
                is_tenant_active=False,
                billing_status="unknown",
                suspended_reason="tenant_not_found",
            )

        return TenantAccessState(
            is_tenant_active=bool(store.is_active),
            billing_status=str(store.billing_status) if store.billing_status else "active",
            suspended_reason=store.suspended_reason,
        )
    except Exception as exc:
        logger.error("get_tenant_access_state error for store %s: %s", store_id, exc)
        return TenantAccessState(
            is_tenant_active=False,
            billing_status="unavailable",
            suspended_reason="tenant_state_unavailable",
        )


async def is_tenant_active(db: AsyncSession, store_id: int) -> bool:
    """Compat helper returning only the active/inactive flag."""
    state = await get_tenant_access_state(db, store_id)
    return state.is_tenant_active
