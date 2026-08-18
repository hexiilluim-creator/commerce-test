"""
api/v1/credits_admin.py — Endpoints admin gestion crédits IA

Routes (toutes protégées par X-Internal-Token) :

  POST /admin/credits/trigger-renewal       — Renouvellement mensuel immédiat (tous les tenants)
  POST /admin/credits/trigger-renewal/{id}  — Renouvellement forcé pour un tenant spécifique
  POST /admin/credits/trigger-alerts        — Check alertes 80%/100% immédiat
  POST /admin/credits/grant-bonus           — Octroyer des crédits bonus à un tenant
  GET  /admin/credits/usage/{tenant_id}     — Résumé crédits d'un tenant
  GET  /admin/credits/ledger/{tenant_id}    — Historique complet (ledger) d'un tenant
  GET  /admin/credits/blocked               — Liste des tenants bloqués IA

Usage typique :
  curl -X POST /api/v1/admin/credits/trigger-renewal \\
       -H "X-Internal-Token: $INTERNAL_HEALTH_TOKEN"

  curl -X POST /api/v1/admin/credits/grant-bonus \\
       -H "X-Internal-Token: $INTERNAL_HEALTH_TOKEN" \\
       -H "Content-Type: application/json" \\
       -d '{"tenant_id": 42, "credits": 500, "reason": "geste commercial suite incident"}'
"""
from __future__ import annotations

import hmac
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.database import get_db
from security_overlay.models import TenantUsage
from security_overlay.plan_catalog import get_plan_spec
from services.credit_ledger import (
    allocate_monthly_credits,
    get_ledger_history,
    get_usage_summary,
    grant_bonus_credits,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/credits", tags=["Admin — Crédits IA"])


# ══════════════════════════════════════════════════════════════════════════════
# Auth
# ══════════════════════════════════════════════════════════════════════════════

def _require_internal_token(
    request: Request,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
) -> None:
    """Autorise soit un X-Internal-Token valide (cron/CLI, cf. docstring module),
    soit une session super_admin authentifiée (dashboard SuperAdmin.jsx).

    Avant ce correctif, ces routes n'acceptaient QUE le X-Internal-Token — un
    secret ops qui ne doit jamais être exposé à un client navigateur. Le
    dashboard Super Admin les appelait donc sans jamais pouvoir s'authentifier
    (403 systématique). On ne met pas le secret côté frontend : on ajoute un
    second chemin d'auth basé sur le rôle JWT, cohérent avec super_admin.py.

    FIX v8 : distinguer 401 (aucun credential présenté) de 403 (credential
    invalide). Le test ``test_credits_monthly_stats_with_months_param`` envoyait
    un token super-admin valide ; le 401 venait du fait que ``current_user``
    n'avait pas encore été appelé avant cette dépendance, donc ``request.state``
    n'avait pas de ``role``. On appelle explicitement le resolver de tenant.
    """
    if x_internal_token and settings.INTERNAL_HEALTH_TOKEN and hmac.compare_digest(
        x_internal_token, settings.INTERNAL_HEALTH_TOKEN
    ):
        return
    has_credentials = bool(x_internal_token) or bool(getattr(request.state, "user_id", None))
    try:
        from middleware.tenant import current_user_role as _cur_role
        role = _cur_role.get()
    except LookupError:
        role = getattr(request.state, "role", None)
    if role == "super_admin":
        return
    # Pas de credential du tout -> 401 (avec WWW-Authenticate pour clients)
    if not has_credentials and role is None:
        raise HTTPException(
            status_code=401,
            detail="Authentification requise",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Credential présenté mais rôle insuffisant -> 403
    raise HTTPException(status_code=403, detail="X-Internal-Token manquant ou r\xc3\xb4le insuffisant")


# ══════════════════════════════════════════════════════════════════════════════
# Schemas
# ══════════════════════════════════════════════════════════════════════════════

class BonusBody(BaseModel):
    tenant_id: int = Field(..., description="ID du store / tenant")
    credits: int = Field(..., ge=1, le=100_000, description="Crédits à octroyer")
    reason: str = Field(..., min_length=5, max_length=300, description="Raison (audit)")
    created_by: str = Field("admin", description="Identifiant de l'opérateur")


class RenewalBody(BaseModel):
    dry_run: bool = Field(False, description="Si True : simule sans écrire en DB")


class TenantRenewalBody(BaseModel):
    plan_code: str | None = Field(None, description="Forcer un plan_code (défaut : plan actif)")
    dry_run: bool = Field(False, description="Si True : simule sans écrire en DB")


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _now_utc() -> datetime:
    return datetime.now(UTC)


def _period_start() -> datetime:
    now = _now_utc()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _period_end() -> datetime:
    now = _now_utc()
    if now.month == 12:
        next_m = now.replace(year=now.year + 1, month=1, day=1)
    else:
        next_m = now.replace(month=now.month + 1, day=1)
    return (next_m - timedelta(seconds=1)).replace(
        hour=23, minute=59, second=59, microsecond=0
    )


async def _get_active_tenants(db: AsyncSession) -> list[tuple[int, str]]:
    from security_overlay.models import SaaSSubscription
    rows = (await db.execute(
        select(SaaSSubscription.tenant_id, SaaSSubscription.billing_plan_code)
        .where(SaaSSubscription.status.in_(["active", "trialing"]))
        .distinct()
    )).fetchall()
    return [(r.tenant_id, r.billing_plan_code) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/trigger-renewal")
async def trigger_renewal_all(
    body: RenewalBody = RenewalBody(),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_internal_token),
):
    """
    Déclenche le renouvellement mensuel immédiat pour tous les tenants actifs.
    Équivalent manuel de la tâche Celery Beat (1er du mois 00:05 UTC).
    Utile pour migrations initiales, tests de smoke, corrections manuelles.
    """
    tenants = await _get_active_tenants(db)
    if not tenants:
        return {"status": "no_active_tenants", "renewed": [], "errors": []}

    period_start = _period_start()
    period_end = _period_end()
    renewed = []
    errors = []

    for tenant_id, plan_code in tenants:
        try:
            spec = get_plan_spec(plan_code)
            if body.dry_run:
                renewed.append({
                    "tenant_id": tenant_id,
                    "plan_code": plan_code,
                    "credits": spec.monthly_ai_credits,
                    "dry_run": True,
                })
                continue

            usage = await allocate_monthly_credits(
                db,
                tenant_id=tenant_id,
                plan_code=plan_code,
                period_start=period_start,
                period_end=period_end,
                created_by="admin:trigger-renewal",
            )
            renewed.append({
                "tenant_id": tenant_id,
                "plan_code": plan_code,
                "credits_allocated": usage.ai_credits_allocated,
                "credits_remaining": usage.ai_credits_remaining,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            })
        except Exception as exc:
            logger.exception("admin.trigger_renewal.error tenant=%d", tenant_id)
            errors.append({"tenant_id": tenant_id, "error": str(exc)})

    if not body.dry_run:
        await db.commit()

    logger.info(
        "admin.trigger_renewal.done dry_run=%s renewed=%d errors=%d",
        body.dry_run, len(renewed), len(errors),
    )
    return {
        "status": "done",
        "dry_run": body.dry_run,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "renewed": renewed,
        "errors": errors,
        "summary": {
            "total_tenants": len(tenants),
            "renewed_count": len(renewed),
            "error_count": len(errors),
        },
    }


@router.post("/trigger-renewal/{tenant_id}")
async def trigger_renewal_one(
    tenant_id: int,
    body: TenantRenewalBody = TenantRenewalBody(),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_internal_token),
):
    """
    Renouvellement forcé pour un tenant spécifique.
    Idéal pour corriger un tenant bloqué sans attendre le cron.
    """
    from security_overlay.models import SaaSSubscription

    sub = (await db.execute(
        select(SaaSSubscription)
        .where(
            SaaSSubscription.tenant_id == tenant_id,
            SaaSSubscription.status.in_(["active", "trialing"]),
        )
        .order_by(SaaSSubscription.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not sub and not body.plan_code:
        raise HTTPException(404, f"Aucun abonnement actif pour le tenant {tenant_id}. "
                                 "Spécifiez plan_code pour forcer le renouvellement.")

    plan_code = body.plan_code or sub.billing_plan_code
    spec = get_plan_spec(plan_code)

    period_start = _period_start()
    period_end = _period_end()

    if body.dry_run:
        return {
            "dry_run": True,
            "tenant_id": tenant_id,
            "plan_code": plan_code,
            "credits_that_would_be_allocated": spec.monthly_ai_credits,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        }

    usage = await allocate_monthly_credits(
        db,
        tenant_id=tenant_id,
        plan_code=plan_code,
        period_start=period_start,
        period_end=period_end,
        created_by="admin:trigger-renewal-single",
    )
    await db.commit()

    logger.info(
        "admin.trigger_renewal_one tenant=%d plan=%s credits=%d",
        tenant_id, plan_code, usage.ai_credits_allocated,
    )
    return {
        "status": "renewed",
        "tenant_id": tenant_id,
        "plan_code": plan_code,
        "credits_allocated": usage.ai_credits_allocated,
        "credits_remaining": usage.ai_credits_remaining,
        "is_ai_blocked": usage.is_ai_blocked,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
    }


@router.post("/trigger-alerts")
async def trigger_alerts_check(
    _: None = Depends(_require_internal_token),
):
    """
    Déclenche le check alertes 80%/100% immédiatement.
    Équivalent manuel de la tâche Celery Beat horaire.
    """
    try:
        from services.tasks_credit_renewal import run_alerts_check_now
        result = run_alerts_check_now()
        return {"status": "done", **result}
    except Exception as exc:
        logger.exception("admin.trigger_alerts.error")
        raise HTTPException(500, f"Erreur lors du check alertes : {exc}")


@router.post("/grant-bonus")
async def grant_bonus(
    body: BonusBody,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_internal_token),
):
    """
    Octroie des crédits bonus à un tenant (geste commercial, correction support, promo).
    Enregistré dans le credit_ledger (entry_type='bonus') pour audit complet.
    Réactive l'IA automatiquement si elle était bloquée.
    """
    try:
        usage = await grant_bonus_credits(
            db,
            tenant_id=body.tenant_id,
            credits=body.credits,
            reason=body.reason,
            created_by=body.created_by,
        )
        await db.commit()

        logger.info(
            "admin.grant_bonus tenant=%d credits=%d reason=%s by=%s",
            body.tenant_id, body.credits, body.reason, body.created_by,
        )
        return {
            "status": "credited",
            "tenant_id": body.tenant_id,
            "credits_granted": body.credits,
            "credits_remaining": usage.ai_credits_remaining,
            "credits_allocated": usage.ai_credits_allocated,
            "is_ai_blocked": usage.is_ai_blocked,
            "reason": body.reason,
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.exception("admin.grant_bonus.error tenant=%d", body.tenant_id)
        raise HTTPException(500, f"Erreur lors de l'octroi des crédits : {exc}")


@router.get("/usage/{tenant_id}")
async def get_tenant_usage(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_internal_token),
):
    """Résumé temps réel des crédits IA pour un tenant."""
    summary = await get_usage_summary(db, tenant_id)
    return {"tenant_id": tenant_id, **summary}


@router.get("/ledger/{tenant_id}")
async def get_tenant_ledger(
    tenant_id: int,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_internal_token),
):
    """Historique complet des mouvements de crédits d'un tenant (append-only)."""
    history = await get_ledger_history(db, tenant_id, limit=limit)
    return {
        "tenant_id": tenant_id,
        "count": len(history),
        "entries": history,
    }


@router.get("/blocked")
async def list_blocked_tenants(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_internal_token),
):
    """
    Liste tous les tenants dont l'IA est actuellement bloquée (crédits épuisés).
    Utile pour le support et la supervision.
    """
    now = _now_utc()
    rows = (await db.execute(
        select(TenantUsage).where(
            TenantUsage.period_start <= now,
            TenantUsage.period_end >= now,
            TenantUsage.ai_blocked_at.isnot(None),
            TenantUsage.ai_reactivated_at.is_(None),
        ).order_by(TenantUsage.ai_blocked_at)
    )).scalars().all()

    blocked = [
        {
            "tenant_id": r.tenant_id,
            "plan_code": r.plan_code,
            "ai_credits_allocated": r.ai_credits_allocated,
            "ai_credits_used": r.ai_credits_used,
            "usage_pct": round(r.usage_pct * 100, 1),
            "ai_blocked_at": r.ai_blocked_at.isoformat() if r.ai_blocked_at else None,
            "period_end": r.period_end.isoformat() if r.period_end else None,
        }
        for r in rows
    ]

    return {
        "total_blocked": len(blocked),
        "tenants": blocked,
    }


# CTO audit fix: SuperAdmin.jsx calls /admin/credits/stats?months=N — expose
# both routes pointing at the same handler so the dashboard widget renders.
@router.get("/stats")
@router.get("/stats/monthly")
async def get_monthly_stats(
    months: int = 6,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_internal_token),
):
    """
    Consommation mensuelle de crédits IA agrégée par plan — derniers N mois.

    Retourne une liste de mois avec la consommation totale par plan_code.
    Format conçu pour alimenter un BarChart Recharts côté frontend.

    Exemple de réponse :
      {
        "months": [
          {
            "month": "2026-01",
            "label": "Jan 2026",
            "starter": 1200,
            "business": 4800,
            "premium": 3100,
            "pro_whatsapp": 7400,
            "total": 16500
          },
          ...
        ],
        "plans": ["starter", "business", "premium", "pro_whatsapp"],
        "grand_total": 98000
      }
    """
    # ── Agrégation : consommations par mois + plan ────────────────
    from models.database import Store
    from security_overlay.models import CreditLedger
    
    if "sqlite" in str(db.bind.engine.url):
        # SQLite: use strftime for grouping
        month_col = func.strftime("%Y-%m", CreditLedger.created_at).label("month")
        # SQLite: abs() is func.abs()
        consumed_col = func.sum(func.abs(CreditLedger.credits_delta)).label("consumed")
    else:
        # PostgreSQL
        month_col = func.to_char(
            func.date_trunc("month", CreditLedger.created_at), "YYYY-MM"
        ).label("month")
        consumed_col = func.sum(func.abs(CreditLedger.credits_delta)).label("consumed")

    # FIX: func.cast(f"{months} months", type_=None) -> SQLAlchemy NullType -> 500.
    # Even with a valid type, asyncpg rejects string "N months" as an interval param.
    # Compute cutoff in Python (same month-arithmetic as all_months loop below).
    _now = datetime.now(UTC)
    _cutoff = _now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for _ in range(months - 1):
        _cutoff = (_cutoff - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    rows = (await db.execute(
        select(
            month_col,
            Store.billing_plan_code.label("plan_code"),
            consumed_col,
        )
        .join(Store, Store.id == CreditLedger.store_id)
        .where(
            CreditLedger.created_at >= _cutoff,
        )
        .group_by(month_col, Store.billing_plan_code)
        .order_by(month_col)
    )).fetchall()

    # ── Reconstruction des mois complets (y compris mois à 0) ────────────────
    from datetime import timedelta as _td

    now = datetime.now(UTC)
    all_months = []
    for i in range(months - 1, -1, -1):
        # 1er du mois, i mois en arrière
        target = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # reculer de i mois
        for _ in range(i):
            target = (target - _td(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        key = target.strftime("%Y-%m")
        label = target.strftime("%b %Y")
        all_months.append({"month": key, "label": label})

    # Map: {(month, plan_code) -> consumed}
    lookup: dict[tuple, int] = {}
    for r in rows:
        lookup[(r.month, r.plan_code or "unknown")] = int(r.consumed or 0)

    known_plans = ["starter", "business", "premium", "pro_whatsapp"]
    grand_total = 0

    result_months = []
    for m in all_months:
        entry = {"month": m["month"], "label": m["label"]}
        month_total = 0
        for plan in known_plans:
            val = lookup.get((m["month"], plan), 0)
            entry[plan] = val
            month_total += val
        entry["total"] = month_total
        grand_total += month_total
        result_months.append(entry)

    return {
        "months": result_months,
        "plans": known_plans,
        "grand_total": grand_total,
    }
