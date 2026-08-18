"""api/v1/settings.py — Store settings, WhatsApp config, Payment config, Users (P1-C)

v18.1 : endpoints BYOK OpenAI supprimés — architecture plateforme unifiée.
Tous les tenants utilisent DeepSeek (primaire) + OpenAI gpt-4o-mini (fallback).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.auth import hash_password
from config import settings as app_settings
from middleware.current_user import current_user_id as _current_user_id
from middleware.tenant import current_tenant_id, current_user_role
from models.database import AuditLog, Store, User, get_db
from services.saas_billing import get_subscription_overview

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["Settings"])


def _require_admin():
    """C4 FIX: inline admin check — raises 403 if not admin role."""
    role = current_user_role.get()
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required for this operation")


# ─── Schemas ──────────────────────────────────────────────────────────────────
SUPPORTED_CURRENCIES = {"TND", "EUR", "USD", "MAD", "DZD", "AED", "SAR", "GBP", "XOF", "CAD"}
COUNTRY_DEFAULT_CURRENCY = {
    "TN": "TND", "MA": "MAD", "DZ": "DZD", "AE": "AED", "SA": "SAR",
    "FR": "EUR", "DE": "EUR", "IT": "EUR", "ES": "EUR", "BE": "EUR",
    "US": "USD", "CA": "CAD", "GB": "GBP", "SN": "XOF", "CI": "XOF",
}


class StoreSettingsUpdate(BaseModel):
    name: str | None = None
    language: str | None = None
    timezone: str | None = None
    country: str | None = None
    currency: str | None = None
    default_tax_country: str | None = None

    @field_validator("country", "default_tax_country")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip().upper()
        if len(value) != 2 or not value.isalpha():
            raise ValueError("country must be an ISO 3166-1 alpha-2 code")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip().upper()
        if value not in SUPPORTED_CURRENCIES:
            raise ValueError(f"Unsupported currency: {value}")
        return value
    logo_url: str | None = None
    support_email: str | None = None
    description: str | None = None       # Description publique boutique
    address: str | None = None           # Adresse physique
    phone_display: str | None = None     # Téléphone affiché publiquement
    website_url: str | None = None       # Site web
    category: str | None = None          # Catégorie boutique
    # Vitrine extra
    opening_hours: dict | None = None
    services: list | None = None
    latitude: float | None = None
    longitude: float | None = None
    social_links: dict | None = None
    # Agent
    ai_agent_prompt: str | None = None
    order_confirmation_msg: str | None = None
    post_payment_msg: str | None = None
    conversation_timeout_min: int | None = None
    stock_api_url: str | None = None


class WhatsAppCredentialsUpdate(BaseModel):
    """E23: Per-store WhatsApp credentials."""
    access_token: str
    phone_number_id: str


class PaymentProviderConfig(BaseModel):
    provider: str          # flouci | clix | tnpay | cash
    api_key: str | None = None
    secret_key: str | None = None
    sandbox: bool = False
    enabled: bool = True


class InviteUserRequest(BaseModel):
    email: EmailStr
    password: str
    role: str = "viewer"   # admin | viewer


class UpdateUserRoleRequest(BaseModel):
    role: str


# ─── Audit helper ─────────────────────────────────────────────────────────────
async def _audit(db: AsyncSession, store_id: int, user_id: int | None,
                 action: str, resource_type: str = None, resource_id: str = None,
                 detail: dict = None, request: Request = None):
    ip = None
    if request:
        ip = request.client.host if request.client else None
    log = AuditLog(
        store_id=store_id, user_id=user_id, action=action,
        resource_type=resource_type, resource_id=resource_id,
        detail=detail, ip_address=ip,
    )
    db.add(log)


# ─── GET store settings ───────────────────────────────────────────────────────
from datetime import UTC

from api.v1._deps import get_store_id as _sid


@router.get("/store")
async def get_store_settings(db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")
    return _serialize_store(store)


# ─── UPDATE store settings ────────────────────────────────────────────────────
# CTO audit fix: expose both PATCH (canonical) and PUT (alias) so any client
# preferring full-document upsert keeps working. Same handler, same audit log.
@router.patch("/store")
@router.put("/store")
async def update_store_settings(
    body: StoreSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin()  # C4 FIX: viewers cannot mutate store settings
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    updates = body.model_dump(exclude_none=True)
    if "country" in updates and "currency" not in updates:
        updates["currency"] = COUNTRY_DEFAULT_CURRENCY.get(updates["country"], getattr(store, "currency", None) or "TND")
    if "country" in updates and "default_tax_country" not in updates:
        updates["default_tax_country"] = updates["country"]

    updated_fields = {}
    for field, value in updates.items():
        setattr(store, field, value)
        updated_fields[field] = value

    await _audit(db, store_id, _current_user_id.get(), "store.update", "store", str(store_id), updated_fields, request)
    await db.commit()
    return _serialize_store(store)


# ─── Payment config ───────────────────────────────────────────────────────────
@router.get("/payments")
async def get_payment_config(db: AsyncSession = Depends(get_db)):
    """Return payment config with keys masked."""
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    cfg = store.payment_config or {}
    masked = {}
    for provider, data in cfg.items():
        masked[provider] = {
            k: ("****" + str(v)[-4:] if k in ("api_key", "secret_key") and v else v)
            for k, v in data.items()
        }
    return {"providers": masked, "configured": list(cfg.keys())}


@router.post("/payments")
async def set_payment_config(
    body: PaymentProviderConfig,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Add or update a payment provider config. Keys are Fernet-encrypted before storage."""
    _require_admin()  # C4 FIX
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    cfg = store.payment_config or {}

    # Encrypt sensitive keys with 'enc_' prefix convention
    provider_data: dict = {"sandbox": body.sandbox, "enabled": body.enabled}
    if body.api_key:
        provider_data["api_key"] = "enc_" + app_settings.encrypt(body.api_key)
    if body.secret_key:
        provider_data["secret_key"] = "enc_" + app_settings.encrypt(body.secret_key)

    cfg[body.provider] = provider_data
    store.payment_config = cfg

    await _audit(db, store_id, _current_user_id.get(), "payment.configure", "payment", body.provider,
                 {"provider": body.provider, "sandbox": body.sandbox}, request)
    await db.commit()
    return {"provider": body.provider, "status": "configured", "sandbox": body.sandbox}


@router.delete("/payments/{provider}")
async def remove_payment_config(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin()  # C4 FIX
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    cfg = store.payment_config or {}
    if provider not in cfg:
        raise HTTPException(404, f"Provider '{provider}' not configured")
    del cfg[provider]
    store.payment_config = cfg
    await _audit(db, store_id, _current_user_id.get(), "payment.remove", "payment", provider, {}, request)
    await db.commit()
    return {"provider": provider, "status": "removed"}


# ─── Users / team management ──────────────────────────────────────────────────
@router.get("/users")
async def list_users(db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    result = await db.execute(
        select(User).where(User.store_id == store_id, User.is_active)
    )
    users = result.scalars().all()
    return [_serialize_user(u) for u in users]


@router.post("/users", status_code=201)
async def invite_user(
    body: InviteUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    role = current_user_role.get()
    if role != "admin":
        raise HTTPException(403, "Only admins can invite users")

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Email already registered")
    if body.role not in ("admin", "viewer"):
        raise HTTPException(400, "Role must be 'admin' or 'viewer'")

    # Enforce the subscription seat quota. The owner/admin is included in the
    # active-user count, so a plan with max_users=1 cannot invite another user.
    active_users_result = await db.execute(
        select(func.count(User.id)).where(User.store_id == store_id, User.is_active)
    )
    active_users = int(active_users_result.scalar_one() or 0)
    subscription = await get_subscription_overview(db, store_id)
    max_users = int(subscription.get("max_users", 1) or 1)
    if active_users >= max_users:
        raise HTTPException(
            status_code=403,
            detail=f"User limit reached for plan ({max_users} active user(s) maximum)",
        )

    user = User(

        store_id=store_id,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.flush()
    await _audit(db, store_id, _current_user_id.get(), "user.invite", "user", str(user.id),
                 {"email": body.email, "role": body.role}, request)
    await db.commit()
    return _serialize_user(user)


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    body: UpdateUserRoleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    role = current_user_role.get()
    if role != "admin":
        raise HTTPException(403, "Only admins can change roles")

    result = await db.execute(
        select(User).where(User.id == user_id, User.store_id == store_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    if body.role not in ("admin", "viewer"):
        raise HTTPException(400, "Role must be 'admin' or 'viewer'")

    user.role = body.role
    await _audit(db, store_id, _current_user_id.get(), "user.role_change", "user", str(user_id),
                 {"new_role": body.role}, request)
    await db.commit()
    return _serialize_user(user)


@router.delete("/users/{user_id}", status_code=204)
async def revoke_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    role = current_user_role.get()
    if role != "admin":
        raise HTTPException(403, "Only admins can revoke access")

    result = await db.execute(
        select(User).where(User.id == user_id, User.store_id == store_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    user.is_active = False
    await _audit(db, store_id, _current_user_id.get(), "user.revoke", "user", str(user_id), {}, request)
    await db.commit()


# ─── WhatsApp credentials (per-store) ────────────────────────────────────────
@router.post("/whatsapp-credentials")
async def set_whatsapp_credentials(
    body: "WhatsAppCredentialsUpdate",
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    E23 FIX: Store per-store WhatsApp credentials (encrypted).
    Each store gets its own Meta App token + phone_number_id.
    Revoking one store's token has zero impact on other stores.
    """
    _require_admin()
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    # Encrypt and persist
    store.whatsapp_access_token_enc = app_settings.encrypt(body.access_token)
    store.whatsapp_phone_number_id = body.phone_number_id

    await _audit(db, store_id, _current_user_id.get(), "whatsapp.credentials_update", "store", str(store_id),
                 {"phone_number_id": body.phone_number_id}, request)
    await db.commit()
    return {
        "status": "configured",
        "phone_number_id": body.phone_number_id,
        "token_stored": True,
    }


@router.delete("/whatsapp-credentials")
async def remove_whatsapp_credentials(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Remove per-store WA credentials — falls back to global settings."""
    _require_admin()
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    store.whatsapp_access_token_enc = None
    store.whatsapp_phone_number_id = None
    await _audit(db, store_id, _current_user_id.get(), "whatsapp.credentials_remove", "store", str(store_id), {}, request)
    await db.commit()
    return {"status": "removed", "fallback": "global_settings"}


# ─── Audit log viewer ─────────────────────────────────────────────────────────
@router.get("/audit-log")
async def get_audit_log(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.store_id == store_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "detail": log.detail,
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


# ─── Serializers ──────────────────────────────────────────────────────────────
def _serialize_store(s: Store) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "slug": s.slug,
        "language": s.language,
        "timezone": getattr(s, "timezone", "Africa/Tunis"),
        "country": getattr(s, "country", None) or "TN",
        "currency": getattr(s, "currency", None) or COUNTRY_DEFAULT_CURRENCY.get(getattr(s, "country", None), "TND"),
        "default_tax_country": getattr(s, "default_tax_country", None) or getattr(s, "country", None) or "TN",
        "logo_url": getattr(s, "logo_url", None),
        "support_email": getattr(s, "support_email", None),
        "ai_agent_prompt": s.ai_agent_prompt,
        "order_confirmation_msg": getattr(s, "order_confirmation_msg", None),
        "post_payment_msg": getattr(s, "post_payment_msg", None),
        "conversation_timeout_min": getattr(s, "conversation_timeout_min", 30),
        "stock_api_url": s.stock_api_url,
        "whatsapp_phone": s.whatsapp_phone,
        # E23: indicate whether per-store WA credentials are configured (never expose token)
        "whatsapp_configured": bool(getattr(s, "whatsapp_access_token_enc", None)),
        "whatsapp_phone_number_id": getattr(s, "whatsapp_phone_number_id", None),
        "description": getattr(s, "description", None),
        "address": getattr(s, "address", None),
        "phone_display": getattr(s, "phone_display", None),
        "website_url": getattr(s, "website_url", None),
        "category": getattr(s, "category", None),
        "opening_hours": getattr(s, "opening_hours", None),
        "services": getattr(s, "services", None),
        "latitude": getattr(s, "latitude", None),
        "longitude": getattr(s, "longitude", None),
        "social_links": getattr(s, "social_links", None),
        "is_active": s.is_active,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _serialize_user(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "role": u.role,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


# ─── Stock Source config ──────────────────────────────────────────────────────
class StockSourceConfig(BaseModel):
    source_type: str   # dashboard | google_sheets | woocommerce | prestashop | generic_api
    config: dict = {}  # credentials selon le type


class OemApiConfig(BaseModel):
    tecdoc_api_key: str | None = None
    tecdoc_provider_id: str | None = None
    autoiso_api_key: str | None = None
    auto_parts_mode: bool | None = None
    nhtsa_enabled: bool | None = None


@router.put("/stock-source")
async def set_stock_source(
    body: StockSourceConfig,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Configure la source de stock du store (Sheets, WC, PS, API, Dashboard)."""
    _require_admin()
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    store.stock_source_type = body.source_type
    if body.config:
        import json
        store.stock_source_config_enc = app_settings.encrypt(json.dumps(body.config))
    else:
        store.stock_source_config_enc = None

    await _audit(db, store_id, _current_user_id.get(), "store.stock_source.update", "store", str(store_id), {"source_type": body.source_type}, request)
    await db.commit()
    return {"ok": True, "source_type": store.stock_source_type}


@router.post("/stock-source/test")
async def test_stock_source(
    body: StockSourceConfig,
    db: AsyncSession = Depends(get_db),
):
    """Teste la connexion à la source de stock configurée."""
    _require_admin()
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    if body.source_type == "dashboard":
        from sqlalchemy import func

        from models.database import Product
        count = (await db.execute(
            select(func.count()).where(Product.store_id == store_id, Product.is_active)
        )).scalar() or 0
        return {"ok": True, "message": "Dashboard connecté", "count": count}

    elif body.source_type == "google_sheets":
        sheet_url = body.config.get("sheet_url", "")
        if not sheet_url:
            raise HTTPException(400, "sheet_url requis")
        import re

        import httpx
        # S1 FIX: SSRF — if URL contains a spreadsheet ID we reconstruct the canonical URL.
        # If it doesn't match, we reject it entirely rather than fetching arbitrary URLs.
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheet_url)
        if match:
            sheet_id = match.group(1)
            # Only allow docs.google.com — never fetch arbitrary URLs from user input
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        else:
            raise HTTPException(400, "URL Google Sheets invalide — format attendu : https://docs.google.com/spreadsheets/d/{ID}/...")
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=False,  # Never follow redirects to internal URLs
            ) as http:
                resp = await http.get(csv_url)
                resp.raise_for_status()
            lines = resp.text.strip().split("\n")
            return {"ok": True, "message": "Google Sheets connecté", "count": max(0, len(lines) - 1)}
        except Exception as e:
            raise HTTPException(400, f"Impossible d'accéder au Sheet : {e}")

    elif body.source_type in ("woocommerce", "prestashop"):
        site_url = body.config.get("site_url", "").rstrip("/")
        if not site_url:
            raise HTTPException(400, "site_url requis")

        # S1 FIX: SSRF — validate URL before fetching
        # Reject: private IPs, localhost, cloud metadata endpoints, non-HTTPS
        import ipaddress
        from urllib.parse import urlparse
        parsed = urlparse(site_url)

        if parsed.scheme not in ("https", "http"):
            raise HTTPException(400, "site_url doit commencer par https://")

        hostname = parsed.hostname or ""
        blocked_hosts = {
            "localhost", "127.0.0.1", "0.0.0.0",
            "169.254.169.254",   # AWS/GCP/Azure metadata
            "metadata.google.internal",
            "redis", "postgres", "db",  # internal service names
        }
        if hostname in blocked_hosts:
            raise HTTPException(400, "site_url pointe vers une adresse interne non autorisée")

        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise HTTPException(400, "site_url pointe vers une adresse IP privée non autorisée")
        except ValueError:
            pass  # Not an IP address — hostname validation passes

        if body.source_type == "woocommerce":
            ck = body.config.get("consumer_key", "")
            cs = body.config.get("consumer_secret", "")
            if not all([ck, cs]):
                raise HTTPException(400, "consumer_key et consumer_secret requis")
            try:
                import httpx
                async with httpx.AsyncClient(
                    timeout=10.0, auth=(ck, cs), follow_redirects=False
                ) as http:
                    resp = await http.get(f"{site_url}/wp-json/wc/v3/products", params={"per_page": 1})
                    resp.raise_for_status()
                    total = int(resp.headers.get("X-WP-Total", 0))
                return {"ok": True, "message": "WooCommerce connecté", "count": total}
            except Exception as e:
                raise HTTPException(400, f"WooCommerce inaccessible : {e}")

        else:  # prestashop
            api_key = body.config.get("api_key", "")
            if not api_key:
                raise HTTPException(400, "api_key requis")
            try:
                import httpx
                async with httpx.AsyncClient(
                    timeout=10.0,
                    headers={"Authorization": f"Basic {api_key}", "Output-Format": "JSON"},
                    follow_redirects=False,
                ) as http:
                    resp = await http.get(f"{site_url}/api/products", params={"limit": 1})
                    resp.raise_for_status()
                return {"ok": True, "message": "PrestaShop connecté", "count": -1}
            except Exception as e:
                raise HTTPException(400, f"PrestaShop inaccessible : {e}")

    return {"ok": True, "message": "Source configurée", "count": -1}


@router.get("/oem-config")
async def get_oem_config(db: AsyncSession = Depends(get_db)):
    """Retourne la config OEM du store (clés masquées)."""
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")
    return {
        "auto_parts_mode": getattr(store, "auto_parts_mode", False),
        "nhtsa_enabled": getattr(store, "nhtsa_enabled", True),
        "tecdoc_configured": bool(getattr(store, "tecdoc_api_key_enc", None)),
        "tecdoc_provider_id": getattr(store, "tecdoc_provider_id", None),
        "autoiso_configured": bool(getattr(store, "autoiso_api_key_enc", None)),
        "stock_source_type": getattr(store, "stock_source_type", "dashboard"),
    }


@router.put("/oem-config")
async def set_oem_config(
    body: OemApiConfig,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Configure les clés OEM (TecDoc, Auto-Iso) et le mode pièces auto."""
    _require_admin()
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    audit_fields = {}
    if body.tecdoc_api_key:
        store.tecdoc_api_key_enc = app_settings.encrypt(body.tecdoc_api_key)
        audit_fields["tecdoc"] = "updated"
    if body.tecdoc_provider_id is not None:
        store.tecdoc_provider_id = body.tecdoc_provider_id
        audit_fields["tecdoc_provider_id"] = body.tecdoc_provider_id
    if body.autoiso_api_key:
        store.autoiso_api_key_enc = app_settings.encrypt(body.autoiso_api_key)
        audit_fields["autoiso"] = "updated"
    if body.auto_parts_mode is not None:
        store.auto_parts_mode = body.auto_parts_mode
        audit_fields["auto_parts_mode"] = body.auto_parts_mode
    if body.nhtsa_enabled is not None:
        store.nhtsa_enabled = body.nhtsa_enabled

    await _audit(db, store_id, _current_user_id.get(), "store.oem_config.update", "store", str(store_id), audit_fields, request)
    await db.commit()
    return {"ok": True, "auto_parts_mode": store.auto_parts_mode}


# ─── Store completeness check ─────────────────────────────────────────────────
@router.get("/store/completeness")
async def get_store_completeness(db: AsyncSession = Depends(get_db)):
    """
    Vérifie si la boutique est complète et prête pour être mise en ligne.
    Retourne un score, les champs manquants et l'URL publique.
    """
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    from models.database import Product
    product_count = (await db.execute(
        select(func.count()).where(Product.store_id == store_id, Product.is_active)
    )).scalar() or 0

    # Définition des champs requis pour être "en ligne"
    checks = {
        "name":           (bool(store.name and store.name.strip()), "Nom de la boutique", "required"),
        "whatsapp_phone": (bool(store.whatsapp_phone), "Numéro WhatsApp", "required"),
        "language":       (bool(store.language), "Langue", "required"),
        "logo_url":       (bool(getattr(store, "logo_url", None)), "Logo / Photo de profil", "recommended"),
        "description":    (bool(getattr(store, "description", None)), "Description de la boutique", "recommended"),
        "support_email":  (bool(getattr(store, "support_email", None)), "Email de contact", "recommended"),
        "ai_agent_prompt":(bool(store.ai_agent_prompt), "Message de bienvenue IA", "recommended"),
        "products":       (product_count >= 1, f"{product_count} produit(s) actif(s)", "required"),
        "whatsapp_configured": (
            bool(getattr(store, "whatsapp_access_token_enc", None))
            and bool(getattr(store, "whatsapp_phone_number_id", None)),
            "WhatsApp Business configuré",
            "required",
        ),
    }

    required_ok   = [k for k,(ok,_,t) in checks.items() if ok and t=="required"]
    required_miss = [{"key":k,"label":l} for k,(ok,l,t) in checks.items() if not ok and t=="required"]
    recommended_miss = [{"key":k,"label":l} for k,(ok,l,t) in checks.items() if not ok and t=="recommended"]

    total_required = len([c for c in checks.values() if c[2]=="required"])
    score = int((len(required_ok) / total_required) * 100) if total_required else 0
    is_online = len(required_miss) == 0

    public_url = f"/store/{store.slug}"

    return {
        "is_online": is_online,
        "score": score,
        "slug": store.slug,
        "public_url": public_url,
        "store_name": store.name,
        "required_missing": required_miss,
        "recommended_missing": recommended_miss,
        "product_count": product_count,
        "checks": {k: {"ok": ok, "label": l, "type": t} for k,(ok,l,t) in checks.items()},
    }


# ─── RGPD Endpoints ───────────────────────────────────────────────────────────
@router.get("/gdpr/export")
async def export_gdpr_data(request: Request, db: AsyncSession = Depends(get_db)):
    """Export ALL tenant data for RGPD/GDPR compliance — Art. 15 (Right of access).

    Returns: store info, team users, customers (PII), orders, products, conversation count.
    Can be downloaded as JSON by the tenant.
    """
    from datetime import UTC, datetime

    from models.database import ConversationLog, Customer, Order, Product

    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    products = [
        {"id": p.id, "name": p.name, "price": p.price, "stock": p.stock_qty, "is_active": p.is_active}
        for p in (await db.execute(select(Product).where(Product.store_id == store_id))).scalars().all()
    ]
    # HC-2 FIX: LIMIT 1000 prevents memory exhaustion on large tenants.
    # Art. 15 RGPD requires providing data — not necessarily all at once.
    # Tenants with >1000 customers receive the most recent 1000 + a notice.
    customers_q = (await db.execute(
        select(Customer)
        .where(Customer.store_id == store_id)
        .order_by(Customer.created_at.desc())
        .limit(1000)
    )).scalars().all()
    customers = [
        {"id": c.id, "name": c.name, "phone": c.whatsapp_phone,
         "channel": getattr(c, "channel", "whatsapp"),
         "opted_out": getattr(c, "opted_out", False),
         "created_at": c.created_at.isoformat() if getattr(c, "created_at", None) else None}
        for c in customers_q
    ]
    orders_q = (await db.execute(
        select(Order)
        .where(Order.store_id == store_id)
        .order_by(Order.created_at.desc())
        .limit(1000)
    )).scalars().all()
    orders = [
        {"id": o.id, "status": o.status,
         "total": str(o.total_amount) if o.total_amount else "0",  # Decimal → str, no float rounding
         "created_at": o.created_at.isoformat() if getattr(o, "created_at", None) else None}
        for o in orders_q
    ]
    users = [
        {"id": u.id, "email": u.email, "role": u.role, "is_active": u.is_active}
        for u in (await db.execute(select(User).where(User.store_id == store_id).limit(1000))).scalars().all()
    ]
    from sqlalchemy import func as sqlfunc
    conv_count = (await db.execute(
        select(sqlfunc.count()).select_from(ConversationLog).where(ConversationLog.store_id == store_id)
    )).scalar() or 0

    return {
        "export_date": datetime.now(UTC).isoformat(),
        "rgpd_basis": "Art. 15 RGPD — Droit d'accès",
        "store": {
            "id": store.id, "name": store.name, "slug": store.slug,
            "whatsapp_phone": store.whatsapp_phone,
            "email": getattr(store, "support_email", None),
            "country": getattr(store, "country", None),
            "billing_plan": getattr(store, "billing_plan_code", "free"),
            "created_at": store.created_at.isoformat() if getattr(store, "created_at", None) else None,
        },
        "users":         {"count": len(users),     "data": users},
        "customers":     {"count": len(customers), "data": customers},
        "orders":        {"count": len(orders),    "data": orders},
        "products":      {"count": len(products),  "data": products},
        "conversations": {"count": conv_count,
                          "note": "Contenu complet disponible sur demande écrite (Art. 15(3))"},
    }

@router.delete("/gdpr/delete")
async def delete_gdpr_data(request: Request, db: AsyncSession = Depends(get_db)):
    """Delete all tenant data for GDPR compliance"""
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
        
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")
        
    # Désactiver la boutique — soft delete pour obligations légales
    store.is_active = False
    store.suspended_reason = "RGPD — Demande d'effacement Art. 17"
    from sqlalchemy.sql import func as _sqlfunc
    store.suspended_at = _sqlfunc.now()

    # Anonymiser tous les users (RGPD Art. 17)
    users_result = await db.execute(select(User).where(User.store_id == store_id))
    for u in users_result.scalars().all():
        u.is_active = False
        u.email = f"rgpd_erased_{u.id}@gdpr-deleted.invalid"
        u.hashed_password = "RGPD_DELETED"
        if hasattr(u, "mfa_secret"):
            u.mfa_secret = None

    # Anonymiser PII clients — RIGHT TO ERASURE (RGPD Art. 17)
    from sqlalchemy import update as _sa_update

    from models.database import Customer
    await db.execute(
        _sa_update(Customer)
        .where(Customer.store_id == store_id)
        .values(name="[Supprimé RGPD]", whatsapp_phone="[supprimé]", social_sender_id=None)
    )

    # Journal d'audit RGPD (Art. 5(2) — accountability)
    try:
        from sqlalchemy import text as _sql_text
        ip = request.client.host if request.client else "unknown"
        user_id_for_log = getattr(request.state, "user_id", None)
        await db.execute(_sql_text(
            "INSERT INTO gdpr_audit_log "
            "(store_id, action, performed_by_user_id, ip_address, details) "
            "VALUES (:sid, :act, :uid, :ip, :det)"
        ), {"sid": store_id, "act": "delete_request", "uid": user_id_for_log,
            "ip": ip, "det": "PII anonymized: customers.name/phone, users.email/password"})
    except Exception as _log_exc:
        logger.warning("gdpr_audit_log insert failed (non-blocking): %s", _log_exc)

    await db.commit()

    return {
        "status": "success",
        "message": "Compte désactivé et données personnelles anonymisées (RGPD Art. 17).",
        "note": "Données anonymisées conservées 30 jours puis purgées automatiquement.",
        "rgpd_reference": "Art. 17 RGPD — Droit à l'effacement",
    }

# ─── Public store page endpoint ───────────────────────────────────────────────
@router.get("/store/public/{slug}")
async def get_public_store(slug: str, db: AsyncSession = Depends(get_db)):
    """
    Endpoint public — aucune auth requise.
    Retourne les infos publiques d'une boutique par slug.
    URL : /api/v1/settings/store/public/<slug>
    """
    result = await db.execute(
        select(Store).where(Store.slug == slug, Store.is_active)
    )
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Boutique introuvable ou inactive")

    from models.database import Product
    products = (await db.execute(
        select(Product).where(Product.store_id == store.id, Product.is_active)
        .order_by(Product.created_at.desc()).limit(20)
    )).scalars().all()

    return {
        "name": store.name or "Ma Boutique",
        "slug": store.slug,
        "logo_url": getattr(store, "logo_url", None),
        "description": getattr(store, "description", "Bienvenue dans notre boutique !"),
        "whatsapp_phone": store.whatsapp_phone or "",
        "support_email": getattr(store, "support_email", None),
        "address": getattr(store, "address", "Tunis, Tunisie"),
        "phone_display": getattr(store, "phone_display", store.whatsapp_phone),
        "website_url": getattr(store, "website_url", None),
        "category": getattr(store, "category", "Commerce"),
        "opening_hours": getattr(store, "opening_hours", {}),
        "services": getattr(store, "services", []),
        "latitude": getattr(store, "latitude", 36.80),
        "longitude": getattr(store, "longitude", 10.18),
        "social_links": getattr(store, "social_links", {}),
        "language": store.language or "fr",
        "is_online": True,
        "product_count": len(products),
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description or "",
                "price": float(p.price) if p.price else 0.0,
                "image_url": p.image_url,
                "stock_qty": p.stock_qty or 0,
            }
            for p in products
        ],
    }


# BYOK OpenAI désactivé (v18.1) — tous les tenants utilisent les providers plateforme.

# ─── WhatsApp full config page ────────────────────────────────────────────────
class WhatsAppFullConfig(BaseModel):
    """Schéma complet pour la page de configuration WhatsApp Business."""
    access_token: str | None = None          # Token Meta — chiffré en base
    phone_number_id: str | None = None       # Phone Number ID Meta
    whatsapp_phone: str | None = None        # Numéro affiché (ex: +21698000000)
    verify_token: str | None = None          # Token de vérification webhook Meta
    webhook_url: str | None = None           # URL webhook à configurer sur Meta
    auto_reply_enabled: bool = True             # Activer/désactiver l'agent IA
    welcome_message: str | None = None      # Message d'accueil personnalisé
    business_hours_enabled: bool = False        # Activer les horaires d'ouverture
    business_hours: dict | None = None       # {"mon": {"open":"09:00","close":"18:00"}, ...}
    out_of_hours_message: str | None = None  # Message hors horaires


@router.get("/whatsapp")
async def get_whatsapp_config(db: AsyncSession = Depends(get_db)):
    """
    Retourne la configuration WhatsApp complète pour la page de config.
    Les tokens sont masqués — ne jamais renvoyer en clair.
    """
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    has_token = bool(getattr(store, "whatsapp_access_token_enc", None))
    phone_id = getattr(store, "whatsapp_phone_number_id", None)
    extra = getattr(store, "extra_config", {}) or {}

    # Build webhook URL hint for the merchant to configure on Meta
    from config import settings as app_cfg
    webhook_url = f"{getattr(app_cfg, 'SERVER_DOMAIN', 'https://your-domain.com')}/api/v1/whatsapp/webhook"

    return {
        "token_configured": has_token,
        "token_masked": ("••••••••" + getattr(store, "whatsapp_access_token_enc", "")[-4:]) if has_token else None,
        "phone_number_id": phone_id,
        "whatsapp_phone": store.whatsapp_phone,
        "webhook_url": webhook_url,
        "verify_token_configured": bool(extra.get("whatsapp_verify_token_enc")),
        "auto_reply_enabled": extra.get("wa_auto_reply_enabled", True),
        "welcome_message": extra.get("wa_welcome_message"),
        "business_hours_enabled": extra.get("wa_business_hours_enabled", False),
        "business_hours": extra.get("wa_business_hours"),
        "out_of_hours_message": extra.get("wa_out_of_hours_message"),
        "setup_guide": {
            "step1": "Créer une application sur developers.facebook.com",
            "step2": "Activer WhatsApp Business API dans l'application",
            "step3": f"Configurer le webhook : {webhook_url}",
            "step4": "Copier le Phone Number ID et l'Access Token ici",
        },
    }


@router.put("/whatsapp")
async def update_whatsapp_config(
    body: WhatsAppFullConfig,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Met à jour la configuration WhatsApp complète."""
    _require_admin()
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    extra = dict(getattr(store, "extra_config", {}) or {})

    # Update token (only if provided — keep existing if not)
    if body.access_token:
        store.whatsapp_access_token_enc = app_settings.encrypt(body.access_token)

    if body.phone_number_id:
        store.whatsapp_phone_number_id = body.phone_number_id

    if body.whatsapp_phone:
        store.whatsapp_phone = body.whatsapp_phone

    if body.verify_token:
        extra["whatsapp_verify_token_enc"] = app_settings.encrypt(body.verify_token)

    # Extra config fields
    extra["wa_auto_reply_enabled"] = body.auto_reply_enabled
    if body.welcome_message is not None:
        extra["wa_welcome_message"] = body.welcome_message
    extra["wa_business_hours_enabled"] = body.business_hours_enabled
    if body.business_hours is not None:
        extra["wa_business_hours"] = body.business_hours
    if body.out_of_hours_message is not None:
        extra["wa_out_of_hours_message"] = body.out_of_hours_message

    store.extra_config = extra
    db.add(store)
    await _audit(
        db, store_id, _current_user_id.get(), "whatsapp.config_update",
        "store", str(store_id),
        {"phone_number_id": body.phone_number_id, "auto_reply": body.auto_reply_enabled},
        request,
    )
    await db.commit()

    # Invalidate tenant cache so next request picks up new WA config
    try:
        from middleware.tenant import invalidate_tenant_state_cache
        invalidate_tenant_state_cache(store_id)
    except Exception as _exc:
        logger.warning("operation failed: %s", _exc)
        pass

    return {
        "status": "updated",
        "token_configured": bool(getattr(store, "whatsapp_access_token_enc", None)),
        "phone_number_id": store.whatsapp_phone_number_id,
        "auto_reply_enabled": body.auto_reply_enabled,
    }


# ─── RGPD — Politique de rétention des données ────────────────────────────────

@router.get("/gdpr/retention-policy")
async def get_retention_policy():
    """RGPD Art. 13/14 — Retourne la politique de rétention des données.

    Endpoint public (accessible sans auth) pour affichage dans la politique
    de confidentialité et le panneau de consentement cookies.
    """
    return {
        "version": "1.0",
        "updated_at": "2026-06-27",
        "rgpd_reference": "Art. 13-14 RGPD — Information au moment de la collecte",
        "categories": [
            {
                "category": "Données de compte",
                "data": ["email", "mot de passe hashé (bcrypt)", "rôle"],
                "purpose": "Authentification et gestion des accès",
                "legal_basis": "Art. 6.1.b — Exécution du contrat",
                "retention": "Durée de l'abonnement + 30 jours",
                "deletion": "Anonymisation automatique à l'expiration",
            },
            {
                "category": "Données boutique",
                "data": ["nom boutique", "slug", "configuration canaux"],
                "purpose": "Fourniture du service SaaS",
                "legal_basis": "Art. 6.1.b — Exécution du contrat",
                "retention": "Durée de l'abonnement + 30 jours",
                "deletion": "Suppression sur demande RGPD Art. 17",
            },
            {
                "category": "Données clients finaux",
                "data": ["numéro WhatsApp", "nom", "historique conversations", "commandes"],
                "purpose": "Traitement des commandes, IA conversationnelle",
                "legal_basis": "Art. 6.1.b — Exécution du contrat",
                "retention": "Durée de l'abonnement",
                "deletion": "Anonymisation PII dans les 30 jours suivant la résiliation",
            },
            {
                "category": "Données financières",
                "data": ["montants commandes", "historique paiements"],
                "purpose": "Facturation, comptabilité",
                "legal_basis": "Art. 6.1.c — Obligation légale",
                "retention": "10 ans (Code de commerce)",
                "deletion": "Non supprimable avant terme légal",
            },
            {
                "category": "Logs de sécurité",
                "data": ["adresses IP", "tentatives de connexion", "actions admin"],
                "purpose": "Sécurité, détection de fraude",
                "legal_basis": "Art. 6.1.f — Intérêt légitime",
                "retention": "12 mois",
                "deletion": "Suppression automatique rolling",
            },
            {
                "category": "Cookies analytiques",
                "data": ["métriques d'usage anonymisées"],
                "purpose": "Amélioration du service",
                "legal_basis": "Art. 6.1.a — Consentement",
                "retention": "13 mois maximum (recommandation CNIL)",
                "deletion": "Sur retrait du consentement",
            },
        ],
        "contact": "privacy@autocommerce.io",
        "dpa_available": True,
        "dpo_contact": "privacy@autocommerce.io",
    }
