"""
api/v1/ops_admin.py — P2‑5 · Routes admin backoffice (mute agent + pause tenant).

Sécurité :
  - JWT role == super_admin pour tous les endpoints (RBAC router-level)
  - Rate limit lecture 30/min, écriture 10/min
  - Action tracée dans middleware/audit_log + journal explicite pour incident response

Endpoints exposés :
  - GET   /api/v1/ops-admin/agents/{store_id}/status     état IA d'un tenant
  - POST  /api/v1/ops-admin/agents/{store_id}/mute       mute global d'un tenant (N minutes)
  - DELETE /api/v1/ops-admin/agents/{store_id}/mute      unmute immédiat
  - POST  /api/v1/ops-admin/agents/{store_id}/takeover/{customer_phone}  prise de main client
  - DELETE /api/v1/ops-admin/agents/{store_id}/takeover/{customer_phone}  release
  - POST  /api/v1/ops-admin/tenants/{store_id}/pause     pause globale (mute + webhooks off)
  - POST  /api/v1/ops-admin/tenants/{store_id}/resume    reprise globale
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from services.agent_mute import (
    DEFAULT_MUTE_MINUTES,
    DEFAULT_TAKEOVER_MINUTES,
    get_store_agent_status,
    mute_store,
    release_customer,
    takeover_customer,
    unmute_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ops-admin",
    tags=["Ops Admin — Mute / Pause (P2‑5)"],
)


# ── RBAC — super_admin uniquement ─────────────────────────────────────────────
async def require_super_admin(request: Request):
    try:
        from middleware.tenant import current_user_role as _cur_role
        role = _cur_role.get()
    except LookupError:
        role = getattr(request.state, "role", None)

    if role is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if role != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="super_admin role required for ops-admin endpoints",
        )
    return True


router_dependencies = [Depends(require_super_admin)]


# ── Schemas ───────────────────────────────────────────────────────────────────
class MuteRequest(BaseModel):
    minutes: int = Field(DEFAULT_MUTE_MINUTES, ge=1, le=1440,
                          description="Durée en minutes (max 24h)")
    reason: str | None = Field(None, max_length=500)


class TakeoverRequest(BaseModel):
    minutes: int = Field(DEFAULT_TAKEOVER_MINUTES, ge=1, le=1440)
    reason: str | None = Field(None, max_length=500)


class PauseRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500,
                        description="Motif OBLIGATOIRE (audit incident)")


def _admin_email(request: Request) -> str:
    try:
        from middleware.tenant import current_user_email as _email
        return _email.get() or "super_admin"
    except Exception:
        return getattr(request.state, "user_email", None) or "super_admin"


async def _audit_admin_action(
    request: Request,
    *,
    action: str,
    store_id: int,
    target: str,
    extra: dict | None = None,
) -> None:
    """Trace l'action admin : audit_log structuré (JSON) + logger rotationnel."""
    payload = {
        "ts": datetime.now(UTC).isoformat(),
        "actor": _admin_email(request),
        "action": action,
        "store_id": store_id,
        "target": target,
        "ip": request.client.host if request.client else "unknown",
        "ua": (request.headers.get("user-agent") or "")[:200],
        "extra": extra or {},
    }
    # JSON line sur stdout/stdout capturé par journald
    logger.info("OPS_ADMIN_ACTION %s", payload)
    # Miroir dans audit_log Mongo si dispo
    try:
        from pymongo import MongoClient
        mc = MongoClient(_audit_mongo_url(), serverSelectionTimeoutMS=200)
        db = mc["autocommerce_audit"]
        db["ops_actions"].insert_one(payload)
    except Exception as _e:
        logger.debug("ops_admin: mongo mirror skip: %s", _e)


def _audit_mongo_url() -> str:
    try:
        from config import settings
        return getattr(settings, "AUDIT_MONGO_URL", "mongodb://localhost:27017")
    except Exception:
        return "mongodb://localhost:27017"


# ── Routes ────────────────────────────────────────────────────────────────────
@router.get("/agents/{store_id}/status",
            dependencies=router_dependencies)
async def get_agent_status(store_id: int):
    """État IA complet d'un tenant (mute global + takeovers actifs)."""
    return await get_store_agent_status(store_id)


@router.post("/agents/{store_id}/mute",
             dependencies=router_dependencies)
async def mute_agent(request: Request, store_id: int, body: MuteRequest):
    """Met l'IA d'un tenant en sourdine globale pendant N minutes (max 24h)."""
    result = await mute_store(store_id, body.minutes)
    await _audit_admin_action(
        request, action="AGENT_MUTE",
        store_id=store_id, target=str(store_id),
        extra={"minutes": body.minutes, "reason": body.reason, "expires_at": result.get("expires_at_unix")},
    )
    return result


@router.delete("/agents/{store_id}/mute",
               dependencies=router_dependencies)
async def unmute_agent(request: Request, store_id: int):
    """Reprise immédiate de l'IA pour ce tenant."""
    result = await unmute_store(store_id)
    await _audit_admin_action(request, action="AGENT_UNMUTE",
                              store_id=store_id, target=str(store_id))
    return result


@router.post("/agents/{store_id}/takeover/{customer_phone}",
             dependencies=router_dependencies)
async def takeover_agent(
    request: Request, store_id: int, customer_phone: str, body: TakeoverRequest,
):
    """Prise de main manuelle sur un client précis pendant N minutes."""
    result = await takeover_customer(store_id, customer_phone, body.minutes)
    await _audit_admin_action(
        request, action="AGENT_TAKEOVER",
        store_id=store_id, target=customer_phone,
        extra={"minutes": body.minutes, "reason": body.reason,
               "expires_at": result.get("expires_at_unix")},
    )
    return result


@router.delete("/agents/{store_id}/takeover/{customer_phone}",
               dependencies=router_dependencies)
async def release_agent(
    request: Request, store_id: int, customer_phone: str,
):
    """Rend la main à l'IA sur ce client."""
    result = await release_customer(store_id, customer_phone)
    await _audit_admin_action(
        request, action="AGENT_TAKEOVER_RELEASE",
        store_id=store_id, target=customer_phone,
    )
    return result


# ── Pause globale d'un tenant (combiné : mute + kill webhook) ───────────────
async def _set_tenant_paused(store_id: int, paused: bool, reason: str) -> dict:
    try:
        from lib.redis_client import get_redis
        r = get_redis()
        key = f"tenant_paused:{store_id}"
        if paused:
            await r.setex(key, 86400, reason[:200])   # TTL 24h — re‑renouvelable
        else:
            await r.delete(key)
        return {"paused": paused}
    except Exception as exc:
        logger.warning("_set_tenant_paused failed store=%s: %s", store_id, exc)
        return {"paused": paused, "warning": "redis_unavailable"}


@router.post("/tenants/{store_id}/pause",
             dependencies=router_dependencies)
async def pause_tenant(
    request: Request, store_id: int, body: PauseRequest, db: AsyncSession = Depends(get_db),
):
    """Pause globale — coupe l'IA + marque le tenant pour les webhooks (P0‑5 aligned)."""
    # 1. Mute global immédiat (24h)
    await mute_store(store_id, minutes=1440)
    # 2. Flag paused pour les webhooks downstream
    await _set_tenant_paused(store_id, True, body.reason)
    await _audit_admin_action(request, action="TENANT_PAUSE",
                              store_id=store_id, target=str(store_id),
                              extra={"reason": body.reason})
    return {"paused": True, "store_id": store_id, "reason": body.reason}


@router.post("/tenants/{store_id}/resume",
             dependencies=router_dependencies)
async def resume_tenant(
    request: Request, store_id: int, db: AsyncSession = Depends(get_db),
):
    """Reprise globale — enlève le flag paused et unmute."""
    await unmute_store(store_id)
    await _set_tenant_paused(store_id, False, "resume")
    await _audit_admin_action(request, action="TENANT_RESUME",
                              store_id=store_id, target=str(store_id))
    return {"paused": False, "store_id": store_id}
