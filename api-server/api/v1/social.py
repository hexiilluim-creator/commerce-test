"""api/v1/social.py — BYOK réseaux sociaux : Instagram, Facebook, TikTok

Chaque réseau dispose de :
  - GET  /social/{network}/status   -> statut de connexion (token configuré ou non)
  - POST /social/{network}/connect  -> sauvegarder le token (chiffré Fernet)
  - DELETE /social/{network}        -> révoquer le token

Les tokens ne sont jamais retournés en clair — uniquement les métadonnées
(username, page_name, account_id, etc.) et le statut connected: bool.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings as app_settings
from middleware.current_user import current_user_id as _current_user_id
from middleware.tenant import current_tenant_id, current_user_role
from models.database import AuditLog, Store, get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/social", tags=["Social Media BYOK"])

SocialNetwork = Literal["instagram", "facebook", "tiktok"]

# ── Schémas ───────────────────────────────────────────────────────────────────

class InstagramConnectRequest(BaseModel):
    access_token: str                  # Instagram Graph API token
    account_id: str                    # Instagram Business Account ID
    username: str | None = None    # Affiché dans le dashboard

class FacebookConnectRequest(BaseModel):
    access_token: str                  # Page Access Token
    page_id: str                       # Facebook Page ID
    page_name: str | None = None

class TikTokConnectRequest(BaseModel):
    access_token: str                  # TikTok for Business access token
    open_id: str                       # TikTok Open ID (identifiant du compte)
    username: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_admin() -> None:
    if current_user_role.get() != "admin":
        raise HTTPException(403, "Admin role required")


async def _get_store(db: AsyncSession) -> Store:
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")
    return store


async def _audit(db: AsyncSession, store_id: int, action: str,
                 network: str, detail: dict, request: Request) -> None:
    ip = request.client.host if request.client else None
    db.add(AuditLog(
        store_id=store_id,
        user_id=_current_user_id.get(),
        action=action,
        resource_type="social",
        resource_id=network,
        detail=detail,
        ip_address=ip,
    ))


# ── GET /social/status — tous les réseaux d'un coup ─────────────────────────

from api.v1._deps import get_store_id as _sid


@router.get("/status")
async def get_all_social_status(db: AsyncSession = Depends(get_db)):
    """Retourne le statut de connexion des 3 réseaux pour ce store."""
    store = await _get_store(db)
    return {
        "instagram": {
            "connected": bool(store.instagram_token_enc),
            "account_id": store.instagram_account_id,
            "username": store.instagram_username,
        },
        "facebook": {
            "connected": bool(store.facebook_token_enc),
            "page_id": store.facebook_page_id,
            "page_name": store.facebook_page_name,
        },
        "tiktok": {
            "connected": bool(store.tiktok_token_enc),
            "open_id": store.tiktok_open_id,
            "username": store.tiktok_username,
        },
    }


# ── INSTAGRAM ────────────────────────────────────────────────────────────────

@router.post("/instagram/connect")
async def connect_instagram(
    body: InstagramConnectRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Enregistre le token Instagram Graph API (chiffré Fernet)."""
    _require_admin()
    store = await _get_store(db)

    store.instagram_token_enc = app_settings.encrypt(body.access_token)
    store.instagram_account_id = body.account_id
    store.instagram_username = body.username or body.account_id

    await _audit(db, store.id, "social.instagram.connect", "instagram",
                 {"account_id": body.account_id, "username": body.username}, request)
    await db.commit()
    return {
        "network": "instagram",
        "connected": True,
        "account_id": store.instagram_account_id,
        "username": store.instagram_username,
    }


@router.delete("/instagram")
async def disconnect_instagram(request: Request, db: AsyncSession = Depends(get_db)):
    """Révoque le token Instagram — le token est supprimé de la DB."""
    _require_admin()
    store = await _get_store(db)
    store.instagram_token_enc = None
    store.instagram_account_id = None
    store.instagram_username = None
    await _audit(db, store.id, "social.instagram.disconnect", "instagram", {}, request)
    await db.commit()
    return {"network": "instagram", "connected": False}


# ── FACEBOOK ─────────────────────────────────────────────────────────────────

@router.post("/facebook/connect")
async def connect_facebook(
    body: FacebookConnectRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Enregistre le Page Access Token Facebook (chiffré Fernet)."""
    _require_admin()
    store = await _get_store(db)

    store.facebook_token_enc = app_settings.encrypt(body.access_token)
    store.facebook_page_id = body.page_id
    store.facebook_page_name = body.page_name or body.page_id

    await _audit(db, store.id, "social.facebook.connect", "facebook",
                 {"page_id": body.page_id, "page_name": body.page_name}, request)
    await db.commit()
    return {
        "network": "facebook",
        "connected": True,
        "page_id": store.facebook_page_id,
        "page_name": store.facebook_page_name,
    }


@router.delete("/facebook")
async def disconnect_facebook(request: Request, db: AsyncSession = Depends(get_db)):
    _require_admin()
    store = await _get_store(db)
    store.facebook_token_enc = None
    store.facebook_page_id = None
    store.facebook_page_name = None
    await _audit(db, store.id, "social.facebook.disconnect", "facebook", {}, request)
    await db.commit()
    return {"network": "facebook", "connected": False}


# ── TIKTOK ───────────────────────────────────────────────────────────────────

@router.post("/tiktok/connect")
async def connect_tiktok(
    body: TikTokConnectRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Enregistre le token TikTok for Business (chiffré Fernet)."""
    _require_admin()
    store = await _get_store(db)

    store.tiktok_token_enc = app_settings.encrypt(body.access_token)
    store.tiktok_open_id = body.open_id
    store.tiktok_username = body.username or body.open_id

    await _audit(db, store.id, "social.tiktok.connect", "tiktok",
                 {"open_id": body.open_id, "username": body.username}, request)
    await db.commit()
    return {
        "network": "tiktok",
        "connected": True,
        "open_id": store.tiktok_open_id,
        "username": store.tiktok_username,
    }


@router.delete("/tiktok")
async def disconnect_tiktok(request: Request, db: AsyncSession = Depends(get_db)):
    _require_admin()
    store = await _get_store(db)
    store.tiktok_token_enc = None
    store.tiktok_open_id = None
    store.tiktok_username = None
    await _audit(db, store.id, "social.tiktok.disconnect", "tiktok", {}, request)
    await db.commit()
    return {"network": "tiktok", "connected": False}


# ── Utilitaire interne : récupérer le token déchiffré ────────────────────────
# Utilisable par les autres services (ex: poster une story, publier un produit)

def get_decrypted_token(store: Store, network: SocialNetwork) -> str | None:
    """
    Retourne le token déchiffré pour un réseau donné.
    Retourne None si le réseau n'est pas configuré.
    Usage interne uniquement — ne jamais exposer via API.
    """
    enc_field = f"{network}_token_enc"
    enc_value = getattr(store, enc_field, None)
    if not enc_value:
        return None
    try:
        return app_settings.decrypt(enc_value)
    except Exception as _exc:
        logger.error("Failed to decrypt %s token for store %s", network, store.id)
        return None
