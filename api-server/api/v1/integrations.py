"""api/v1/integrations.py — Connecteurs externes

Routes pour configurer les sources de données tierces que l'agent IA peut interroger :
  - Stock API (URL externe pour vérifier disponibilité en temps réel)
  - CRM (webhook entrant / URL d'appel pour enrichir les profils clients)
  - Catalogue API (import produits via URL)
  - Webhook sortant (notifier un système externe à chaque commande)

Pattern BYOK (Bring Your Own Key) : les clés API sont chiffrées en base (Fernet).
L'IA n'a accès qu'aux URLs et peut appeler ces endpoints via le tool registry.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import require_role
from config import settings
from middleware.tenant import current_tenant_id
from models.database import Store, get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations", tags=["Integrations"])

# ── Types de connecteurs supportés ─────────────────────────────────────────────
IntegrationType = Literal[
    "stock_api",          # URL REST pour vérifier stock en temps réel
    "crm_webhook",        # URL pour envoyer les events clients vers un CRM externe
    "catalog_import_url", # URL CSV/JSON pour import automatique produits
    "order_webhook",      # URL notifiée à chaque nouvelle commande
    "payment_notify_url", # URL notifiée après confirmation paiement
    "ai_knowledge_url",   # URL interrogée par l'IA pour des infos métier spécifiques
]

INTEGRATION_META = {
    "stock_api": {
        "label": "API Stock externe",
        "description": "URL REST appelée par l'IA pour vérifier la disponibilité d'un produit en temps réel. Doit retourner JSON avec `available: bool, qty: int`.",
        "example": "https://mon-erp.com/api/v1/stock?sku={sku}",
        "requires_key": True,
    },
    "crm_webhook": {
        "label": "Webhook CRM",
        "description": "URL appelée à chaque nouveau client ou mise à jour de profil. L'agent envoie un POST JSON avec les données client.",
        "example": "https://mon-crm.com/webhooks/autocommerce",
        "requires_key": True,
    },
    "catalog_import_url": {
        "label": "Import catalogue automatique",
        "description": "URL d'un fichier CSV ou JSON contenant vos produits. Synchronisé toutes les 6h ou manuellement.",
        "example": "https://mon-erp.com/export/produits.csv",
        "requires_key": False,
    },
    "order_webhook": {
        "label": "Webhook commandes",
        "description": "URL notifiée à chaque nouvelle commande créée. Utile pour déclencher la préparation dans votre ERP.",
        "example": "https://mon-erp.com/webhooks/new-order",
        "requires_key": True,
    },
    "payment_notify_url": {
        "label": "Notification paiement",
        "description": "URL appelée après confirmation de paiement. Reçoit : order_id, amount, provider, status.",
        "example": "https://mon-erp.com/webhooks/payment-confirmed",
        "requires_key": False,
    },
    "ai_knowledge_url": {
        "label": "Base de connaissance IA",
        "description": "URL interrogée par l'IA quand un client pose une question hors catalogue (FAQ, politique retour, horaires). Doit retourner du texte plain ou JSON avec `answer: str`.",
        "example": "https://mon-site.com/api/faq?q={question}",
        "requires_key": False,
    },
}


# ── Schemas ─────────────────────────────────────────────────────────────────────
class IntegrationConfig(BaseModel):
    url: str
    api_key: str | None = None       # chiffré en base — jamais renvoyé en clair
    enabled: bool = True
    description: str | None = None  # note interne libre

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if v and not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError("L'URL doit commencer par https:// ou http://")
        return v


class IntegrationResponse(BaseModel):
    type: str
    label: str
    description: str
    url: str | None
    api_key_configured: bool
    enabled: bool
    meta_description: str
    example_url: str


def _decrypt_key(enc: str) -> str:
    """Decrypt a stored API key."""
    return settings.decrypt(enc)


def _encrypt_key(plain: str) -> str:
    """Encrypt an API key before storage."""
    return settings.encrypt(plain)


def _get_store_integrations(store: Store) -> dict:
    """Read integrations config from store.stock_api_url and extra_config JSON."""
    integrations = {}
    extra = getattr(store, "extra_config", {}) or {}

    # stock_api_url is stored directly on Store model
    if store.stock_api_url:
        integrations["stock_api"] = {
            "url": store.stock_api_url,
            "api_key_enc": extra.get("stock_api_key_enc"),
            "enabled": extra.get("stock_api_enabled", True),
        }

    # Other integrations stored in extra_config JSON
    for itype in ["crm_webhook", "catalog_import_url", "order_webhook",
                  "payment_notify_url", "ai_knowledge_url"]:
        cfg = extra.get(f"integration_{itype}")
        if cfg:
            integrations[itype] = cfg

    return integrations


# ── GET /integrations — list all configured integrations ────────────────────────
from api.v1._deps import get_store_id as _sid


@router.get("/")
async def list_integrations(db: AsyncSession = Depends(get_db)):
    """
    Liste tous les connecteurs disponibles avec leur état de configuration.
    Retourne le catalogue complet + statut de chaque connecteur pour ce tenant.
    """
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    configured = _get_store_integrations(store)
    response = []

    for itype, meta in INTEGRATION_META.items():
        cfg = configured.get(itype, {})
        response.append({
            "type": itype,
            "label": meta["label"],
            "description": meta["description"],
            "example_url": meta["example"],
            "requires_key": meta["requires_key"],
            "url": cfg.get("url") if cfg else None,
            "api_key_configured": bool(cfg.get("api_key_enc")) if cfg else False,
            "enabled": cfg.get("enabled", False) if cfg else False,
        })

    return {"integrations": response}


# ── GET /integrations/{type} — get single integration config ────────────────────
@router.get("/{integration_type}")
async def get_integration(
    integration_type: str,
    db: AsyncSession = Depends(get_db),
):
    if integration_type not in INTEGRATION_META:
        raise HTTPException(404, f"Type d'intégration inconnu: {integration_type}. "
                                 f"Types valides: {list(INTEGRATION_META.keys())}")

    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    configured = _get_store_integrations(store)
    cfg = configured.get(integration_type, {})
    meta = INTEGRATION_META[integration_type]

    return {
        "type": integration_type,
        "label": meta["label"],
        "description": meta["description"],
        "example_url": meta["example"],
        "url": cfg.get("url") if cfg else None,
        "api_key_configured": bool(cfg.get("api_key_enc")) if cfg else False,
        "enabled": cfg.get("enabled", False) if cfg else False,
    }


# ── PUT /integrations/{type} — configure or update an integration ───────────────
@router.put("/{integration_type}")
async def set_integration(
    integration_type: str,
    body: IntegrationConfig,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _role=require_role("admin"),
):
    """
    Configure un connecteur externe pour ce tenant.
    La clé API est chiffrée avant stockage (Fernet) — jamais loggée ni renvoyée.
    """
    if integration_type not in INTEGRATION_META:
        raise HTTPException(400, f"Type inconnu: {integration_type}")

    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    extra = dict(getattr(store, "extra_config", {}) or {})

    if integration_type == "stock_api":
        # stock_api_url stored directly on Store model
        store.stock_api_url = body.url or None
        if body.api_key:
            extra["stock_api_key_enc"] = _encrypt_key(body.api_key)
        extra["stock_api_enabled"] = body.enabled
    else:
        key = f"integration_{integration_type}"
        existing = extra.get(key, {})
        extra[key] = {
            "url": body.url,
            "api_key_enc": (
                _encrypt_key(body.api_key) if body.api_key
                else existing.get("api_key_enc")   # keep existing key if not updated
            ),
            "enabled": body.enabled,
            "description": body.description,
        }

    store.extra_config = extra
    db.add(store)
    await db.commit()

    logger.info(
        "integration.configured store=%s type=%s enabled=%s url=%s",
        store_id, integration_type, body.enabled,
        body.url[:50] + "..." if body.url and len(body.url) > 50 else body.url
    )

    return {
        "status": "configured",
        "type": integration_type,
        "label": INTEGRATION_META[integration_type]["label"],
        "url": body.url,
        "api_key_configured": bool(body.api_key or (
            extra.get(f"integration_{integration_type}", {}).get("api_key_enc")
            if integration_type != "stock_api"
            else extra.get("stock_api_key_enc")
        )),
        "enabled": body.enabled,
    }


# ── DELETE /integrations/{type} — remove an integration ─────────────────────────
@router.delete("/{integration_type}")
async def remove_integration(
    integration_type: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _role=require_role("admin"),
):
    if integration_type not in INTEGRATION_META:
        raise HTTPException(400, f"Type inconnu: {integration_type}")

    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    extra = dict(getattr(store, "extra_config", {}) or {})

    if integration_type == "stock_api":
        store.stock_api_url = None
        extra.pop("stock_api_key_enc", None)
        extra.pop("stock_api_enabled", None)
    else:
        extra.pop(f"integration_{integration_type}", None)

    store.extra_config = extra
    db.add(store)
    await db.commit()

    return {"status": "removed", "type": integration_type}


# ── POST /integrations/{type}/test — test connectivity ──────────────────────────
@router.post("/{integration_type}/test")
async def test_integration(
    integration_type: str,
    db: AsyncSession = Depends(get_db),
    _role=require_role("admin"),
):
    """
    Teste la connectivité vers l'URL configurée pour ce connecteur.
    Envoie un GET (ou POST vide) et vérifie la réponse HTTP.

    AUDIT FIX (CRITICAL) : cet endpoint n'avait aucun contrôle de rôle
    (contrairement aux endpoints de configuration juste au-dessus, qui
    exigent require_role("admin")) et faisait un appel HTTP direct vers une
    URL fournie par le tenant sans validation — SSRF exploitable par
    n'importe quel utilisateur authentifié du store, avec en prime la clé API
    déchiffrée du marchand envoyée dans le header Authorization vers la cible.
    """
    import httpx

    from services.ssrf_guard import SSRFBlocked, assert_safe_external_url

    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")

    configured = _get_store_integrations(store)
    cfg = configured.get(integration_type)

    if not cfg or not cfg.get("url"):
        raise HTTPException(400, f"Connecteur '{integration_type}' non configuré ou URL manquante")

    url = cfg["url"]
    # Replace template vars with test values for test call
    test_url = url.replace("{sku}", "TEST-SKU").replace("{question}", "test")

    try:
        assert_safe_external_url(test_url)
    except SSRFBlocked as exc:
        raise HTTPException(400, f"URL non autorisée : {exc}")

    headers = {}
    if cfg.get("api_key_enc"):
        api_key = _decrypt_key(cfg["api_key_enc"])
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(test_url, headers=headers)
        return {
            "success": resp.status_code < 500,
            "status_code": resp.status_code,
            "message": f"Réponse HTTP {resp.status_code} reçue",
            "url_tested": test_url[:100],
        }
    except httpx.TimeoutException:
        return {"success": False, "error": "Timeout — l'URL ne répond pas en moins de 10s"}
    except httpx.ConnectError as e:
        return {"success": False, "error": f"Connexion refusée : {str(e)[:100]}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}
