"""
api/v1/credits.py — Endpoints crédits IA

Routes :
  GET  /billing/credits/usage      — résumé temps réel (widget dashboard)
  GET  /billing/credits/history    — journal des mouvements
  POST /billing/credits/top-up     — acheter une recharge
  GET  /billing/credits/packs      — catalogue des packs disponibles
  GET  /billing/credits/plans      — catalogue plans DT avec quotas
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import get_store_id as _sid
from models.database import get_db
from security_overlay.models import CreditTopUpPackModel
from security_overlay.plan_catalog import CREDIT_TOP_UP_PACKS, PLAN_CATALOG
from services.ai_guardrails import get_tenant_credit_stats
from services.credit_ledger import (
    CREDIT_PACKS,
    get_available_packs,
    get_ledger_history,
    get_usage_summary,
    purchase_top_up,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing/credits", tags=["Credits IA"])


class TopUpBody(BaseModel):
    pack_code: str = Field(..., description="starter_50 | growth_200 | business_500 | enterprise_1k")
    reference_id: str | None = Field(None, description="ID transaction paiement")


def _tenant_id_or_401() -> int:
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    return int(store_id)


def _serialize_static_packs() -> list[dict]:
    """Catalogue canonique utilisé par le service de top-up."""
    packs: list[dict] = []
    for pack in get_available_packs():
        credits_amount = int(pack["credits"])
        bonus_credits = int(pack.get("bonus_credits", 0) or 0)
        packs.append(
            {
                "pack_code": pack["pack_id"],
                "display_name": pack.get("label", f"{credits_amount} crédits IA"),
                "credits_amount": credits_amount,
                "bonus_credits": bonus_credits,
                "total_credits": credits_amount + bonus_credits,
                "price_dt": float(pack["price_dt"]),
                "price_usd": float(pack.get("price_usd", 0) or 0),
            }
        )
    return packs


def _rows_use_canonical_pack_codes(rows: Iterable[CreditTopUpPackModel]) -> bool:
    canonical_codes = set(CREDIT_PACKS.keys())
    return all(row.pack_code in canonical_codes for row in rows)


def _normalize_usage_payload(summary: dict, stats: dict) -> dict:
    plan_code = str(summary.get("plan_code") or "free")
    allocated = int(stats.get("allocated", summary.get("credits_monthly_limit", 0)) or 0)
    used = int(stats.get("used", summary.get("credits_used", 0)) or 0)
    remaining = int(stats.get("remaining", summary.get("credits_remaining", 0)) or 0)
    usage_pct = float(stats.get("credits_percent_used") or (round((used / allocated) * 100, 1) if allocated > 0 else 0.0))
    has_active_period = bool(allocated > 0 or plan_code != "free")
    is_ai_blocked = bool(has_active_period and remaining <= 0)

    return {
        "plan_code": plan_code,
        "has_active_period": has_active_period,
        "period": stats.get("period"),
        "reset_date": summary.get("reset_date"),
        "credits_monthly_limit": int(summary.get("credits_monthly_limit", allocated) or allocated),
        "credits_used": used,
        "credits_remaining": remaining,
        "credits_allocated": allocated,
        # Alias attendus par le widget dashboard
        "ai_credits_used": used,
        "ai_credits_remaining": remaining,
        "ai_credits_allocated": allocated,
        "usage_pct": usage_pct,
        "credits_percent_used": usage_pct,
        "is_ai_blocked": is_ai_blocked,
    }


async def _build_usage_payload(tenant_id: int) -> dict:
    summary = await get_usage_summary(tenant_id)
    stats = await get_tenant_credit_stats(tenant_id)
    return _normalize_usage_payload(summary, stats)


@router.get("/usage")
async def get_credit_usage():
    """Résumé temps réel des crédits IA du tenant pour le widget dashboard."""
    tenant_id = _tenant_id_or_401()
    return await _build_usage_payload(tenant_id)


@router.get("/history")
async def get_credit_history(
    limit: int = Query(50, ge=1, le=200),
    entry_type: str | None = Query(None, description="allocation|consumption|purchase|bonus|renewal|expiry|refund|top_up"),
):
    """Journal des mouvements de crédits (append-only)."""
    tenant_id = _tenant_id_or_401()
    history = await get_ledger_history(tenant_id, limit=limit)

    entries: list[dict] = []
    for row in history:
        normalized = dict(row)
        normalized.setdefault("entry_type", normalized.get("event_type"))
        if entry_type and normalized.get("entry_type") != entry_type:
            continue
        entries.append(normalized)

    return {"entries": entries, "count": len(entries)}


@router.post("/top-up")
async def buy_top_up(body: TopUpBody):
    """Recharge de crédits — actuellement indisponible en self-service.

    AUDIT FIX (P0, CTO audit) : cet endpoint créditait auparavant des packs
    de recharge SANS AUCUNE vérification de paiement réelle (ni Stripe, ni
    autre) — `payment_ref` n'était qu'une chaîne libre non vérifiée, jamais
    confrontée à un paiement confirmé. N'importe quel tenant authentifié
    pouvait donc s'auto-créditer des crédits IA illimités gratuitement.
    En attendant l'intégration d'un moyen de paiement réel, ce endpoint est
    désactivé : la recharge se fait manuellement (virement/espèces) via le
    Super Admin — voir /api/v1/billing/contact-sales et
    /api/v1/super-admin/stores/{id}/assign-plan.
    """
    _tenant_id_or_401()
    raise HTTPException(
        503,
        "La recharge de crédits en libre-service est temporairement indisponible. "
        "Contactez-nous par WhatsApp pour activer votre recharge : +216 55 919 598.",
    )


@router.get("/packs")
async def get_top_up_packs(db: AsyncSession = Depends(get_db)):
    """Catalogue des recharges disponibles à l'achat."""
    static_packs = _serialize_static_packs()

    try:
        rows = (
            await db.execute(
                select(CreditTopUpPackModel)
                .where(CreditTopUpPackModel.is_active.is_(True))
                .order_by(CreditTopUpPackModel.rank.asc(), CreditTopUpPackModel.id.asc())
            )
        ).scalars().all()
    except Exception as exc:  # pragma: no cover - fallback runtime safety
        logger.warning("credits.packs db lookup failed, fallbacking to static catalog: %s", exc)
        rows = []

    if not rows:
        return {"packs": static_packs}

    if not _rows_use_canonical_pack_codes(rows):
        logger.warning("credits.packs detected legacy/non-canonical DB pack codes; serving static canonical catalog")
        return {"packs": static_packs}

    packs = [
        {
            "id": row.id,
            "pack_code": row.pack_code,
            "display_name": row.display_name,
            "credits_amount": row.credits_amount,
            "bonus_credits": row.bonus_credits,
            "total_credits": row.credits_amount + row.bonus_credits,
            "price_dt": row.price_dt,
            "price_usd": row.price_usd,
        }
        for row in rows
    ]
    return {"packs": packs}


@router.get("/plans")
async def get_plans_with_credits():
    """Catalogue des plans avec prix DT + quotas crédits."""
    plans = []
    for _code, spec in PLAN_CATALOG.items():
        plans.append({
            "code": spec.code,
            "label": spec.name,
            "price_monthly_dt": spec.price_monthly,
            "price_monthly_usd": getattr(spec, "price_monthly_usd", 0),
            "price_annual_dt": getattr(spec, "price_annual_dt", 0),
            "price_annual_usd": getattr(spec, "price_annual_usd", 0),
            "max_products": getattr(spec, "max_products", 0),
            "max_users": getattr(spec, "max_users", 0),
            "monthly_ai_credits": getattr(spec, "monthly_ai_credits", 0),
            "whatsapp_enabled": "channels.whatsapp" in spec.features,
            "crm_enabled": any(f.startswith("crm.") for f in spec.features),
            "crm_advanced_enabled": "crm.advanced" in spec.features,
            "marketing_enabled": "marketing" in spec.features,
            "omnichannel_enabled": "omnichannel" in spec.features,
            "priority_support_enabled": "priority_support" in spec.features,
            "credit_costs": {
                "text": 1,
                "audio": 5,
                "image": 10,
            },
            "whatsapp_disclaimer": (
                "Les frais Meta WhatsApp sont facturés séparément par Meta."
            ) if "channels.whatsapp" in spec.features else None,
        })
    return {"plans": plans, "top_up_packs": [
        {
            "pack_code": p.pack_id,
            "display_name": f"{p.credits} crédits",
            "credits_amount": p.credits,
            "bonus_credits": 0,
            "total_credits": p.credits,
            "price_dt": p.price,
            "price_usd": 0,
        }
        for p in CREDIT_TOP_UP_PACKS
    ]}
