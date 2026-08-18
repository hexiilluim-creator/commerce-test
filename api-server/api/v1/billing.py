from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from middleware.tenant import current_tenant_id
from models.database import Order, Product, Store, StorePhoneMapping, get_db
from security_overlay.billing_overlay import get_billing_snapshot
from security_overlay.guard import get_guard
from services.saas_billing import (
    create_flouci_payment,
    create_stripe_checkout_session,
    get_subscription_overview,
    handle_flouci_webhook,
    handle_stripe_webhook,
    list_plans_catalog,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["Billing"])

class CheckoutBody(BaseModel):
    plan_code: str = Field(..., description="starter | business | premium | pro_whatsapp")
    success_url: str
    cancel_url: str

def _tenant_id_or_401() -> int:
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    return int(store_id)

from api.v1._deps import get_store_id as _sid


@router.get("/plans")
async def get_public_plans(db: AsyncSession = Depends(get_db)):
    return {"plans": await list_plans_catalog(db)}


@router.get("/whatsapp-gate")
async def whatsapp_gate():
    """Return whether WhatsApp is enabled for the current tenant's plan."""
    tenant_id = _tenant_id_or_401()
    snapshot = await get_billing_snapshot(tenant_id)
    enabled = snapshot.has_feature("channels.whatsapp")
    return {
        "enabled": enabled,
        "plan_code": snapshot.plan_code,
        "required_plan": "pro_whatsapp",
        "required_plan_label": "Pro WhatsApp",
        "monthly_price_dt": 49.99,
        "annual_price_dt": 499.0,
        "disclaimer": "Les frais Meta WhatsApp ne sont pas inclus dans l'abonnement.",
    }

# CTO audit fix: expose both /subscription (canonical) and /subscription-overview
# (alias) — Products.jsx calls /subscription-overview to read plan.features.
@router.get("/subscription")
@router.get("/subscription-overview")
async def get_current_subscription(db: AsyncSession = Depends(get_db)):
    tenant_id = _tenant_id_or_401()
    return await get_subscription_overview(db, tenant_id)

@router.post("/checkout")
async def checkout_subscription(body: CheckoutBody, db: AsyncSession = Depends(get_db)):
    tenant_id = _tenant_id_or_401()
    try:
        url = await create_stripe_checkout_session(db, tenant_id, body.plan_code, body.success_url, body.cancel_url)
        return {"checkout_url": url}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Stripe error: {str(e)}")

@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    if not stripe_signature:
        raise HTTPException(400, "Missing stripe signature")
    
    payload = await request.body()
    try:
        await handle_stripe_webhook(db, payload, stripe_signature)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Stripe webhook error: {str(e)}")
        raise HTTPException(400, f"Webhook error: {str(e)}")

@router.post("/checkout-flouci")
async def checkout_subscription_flouci(body: CheckoutBody, db: AsyncSession = Depends(get_db)):
    """Crée un paiement Flouci pour un abonnement (marché Tunisie/local)."""
    tenant_id = _tenant_id_or_401()
    try:
        url = await create_flouci_payment(
            db, tenant_id, body.plan_code, body.success_url, body.cancel_url
        )
        return {"checkout_url": url}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Flouci error: {str(e)}")

@router.post("/webhook/flouci")
async def flouci_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    headers = dict(request.headers)
    try:
        await handle_flouci_webhook(db, payload, headers)
        return {"status": "success"}
    except ValueError as e:
        logger.error(f"Flouci webhook error: {str(e)}")
        raise HTTPException(400, f"Webhook error: {str(e)}")
    except Exception as e:
        logger.error(f"Flouci webhook unexpected error: {str(e)}")
        raise HTTPException(500, "Webhook processing error")

@router.get("/usage")
async def get_usage_dashboard(db: AsyncSession = Depends(get_db)):
    store_id = _tenant_id_or_401()
    # AUDIT-FIX: dump_stats() takes `store_id`, not `tenant_id` — this call
    # raised TypeError on every request, so /billing/usage never worked.
    ai_stats = await get_guard().dump_stats(store_id=store_id)
    subscription = await get_subscription_overview(db, store_id)
    snapshot = await get_billing_snapshot(store_id)
    
    return {
        "store_id": store_id,
        "plan": {
            "plan_code": snapshot.plan_code,
            "plan_label": snapshot.plan_label,
            "is_paid": snapshot.is_paid,
            "features": sorted(snapshot.features),
        },
        # AUDIT-FIX: dump_stats() returns {"ai_credits": ..., "plan_code": ...,
        # ...}, never "ai"/"limits" — those keys don't exist, KeyError.
        "ai_usage": ai_stats.get("ai_credits", {}),
        "ai_limits": {
            "allocated": ai_stats.get("ai_credits", {}).get("allocated"),
            "remaining": ai_stats.get("ai_credits", {}).get("remaining"),
        },
        "saas_subscription": subscription,
    }

@router.get("/onboarding")
async def get_onboarding_checklist(db: AsyncSession = Depends(get_db)):
    store_id = _tenant_id_or_401()
    store = await db.get(Store, store_id)
    if not store:
        raise HTTPException(404, "Store not found")

    store_configured = bool(store.name and store.language)
    wa_result = await db.execute(
        select(StorePhoneMapping).where(StorePhoneMapping.store_id == store_id, StorePhoneMapping.is_active)
    )
    whatsapp_connected = wa_result.scalar_one_or_none() is not None
    payment_configured = bool(store.payment_config and len(store.payment_config) > 0)

    prod_count = (
        await db.execute(select(func.count()).select_from(Product).where(Product.store_id == store_id, Product.is_active))
    ).scalar()
    first_product_added = (prod_count or 0) > 0

    order_count = (await db.execute(select(func.count()).select_from(Order).where(Order.store_id == store_id))).scalar()
    first_order_received = (order_count or 0) > 0

    subscription = await get_subscription_overview(db, store_id)
    steps = {
        "store_configured": store_configured,
        "whatsapp_connected": whatsapp_connected,
        "payment_configured": payment_configured,
        "first_product_added": first_product_added,
        "first_order_received": first_order_received,
        "plan_selected": subscription.get("billing_plan_code") in {"starter", "business", "premium", "pro_whatsapp"},
        "billing_activated": subscription.get("status") in {"active", "trialing"},
    }

    completed = sum(1 for v in steps.values() if v)
    total = len(steps)
    ready_to_sell = all([store_configured, whatsapp_connected, payment_configured, first_product_added])
    return {
        "steps": steps,
        "completed": completed,
        "total": total,
        "percent": round(completed / total * 100),
        "ready_to_sell": ready_to_sell,
        "next_step": next((k for k, v in steps.items() if not v), None),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CRIT-2 FIX (Audit CTO V18) — Endpoint de transparence BYOK
# ─────────────────────────────────────────────────────────────────────────────
# Contexte : Le système BYOK OpenAI (Bring Your Own Key) a été désactivé
# en v18.1 et officiellement supprimé en v15 (migration 0029).
# Des tenants avaient potentiellement soumis une clé API en croyant activer
# le BYOK. Sans cet endpoint, aucune communication n'était possible sur l'état
# réel de la feature.
# Cet endpoint permet :
#   1. Au frontend de ne pas afficher de formulaire BYOK (évite la confusion UX).
#   2. Aux tenants d'être informés que leurs clés, si soumises, ne sont pas utilisées.
#   3. À l'audit de prouver la transparence contractuelle (pas de feature silencieusement
#      désactivée sans information).

@router.get(
    "/byok-status",
    summary="Statut du BYOK (Bring Your Own Key) OpenAI",
    description=(
        "Retourne l'état du système BYOK pour ce tenant. "
        "Le BYOK OpenAI a été officiellement désactivé en v18.1 et les colonnes "
        "supprimées en v15 (migration 0029). Tous les tenants utilisent les providers "
        "plateforme (DeepSeek + OpenAI gpt-4o-mini). "
        "Consultez votre plan pour connaître les quotas inclus."
    ),
    tags=["Billing"],
)
async def get_byok_status():
    """Statut BYOK — toujours désactivé depuis v18.1 / colonnes supprimées en v15."""
    return {
        "byok_enabled": False,
        "reason": "byok_removed_v15",
        "message": (
            "Le BYOK OpenAI a été supprimé en v15. "
            "Tous les tenants utilisent les providers plateforme (DeepSeek + OpenAI). "
            "Si vous aviez soumis une clé API, elle a été supprimée de nos bases de données."
        ),
        "providers_platform": ["deepseek-chat", "gpt-4o-mini"],
        "docs_url": "https://docs.autocommerce.ma/ia/providers",
    }
