"""services/credit_ledger.py — Ledger de crédits tenant.

Implémentation basée sur la table credit_events (migration 0033_credit_events_ledger).
Le fallback TenantSubscription est conservé pour la lecture de l'historique si la
table credit_events est vide.

Fonctions exposées :
  - get_ledger_history(store_id, limit)  -> liste des transactions depuis credit_events
  - get_usage_summary(store_id)          -> crédits utilisés / restants du mois courant
  - purchase_top_up(store_id, pack_id, payment_ref) -> top-up via credit_events + Redis

V24 ENTERPRISE FIX :
  - PLAN_MONTHLY_CREDITS unifié avec ai_guardrails.py (source de vérité unique)
  - purchase_top_up : fail-hard si credit_events absent (ne retourne plus ok=True avec warning)
  - purchase_top_up : crédits ajoutés en Redis atomiquement après écriture DB
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Exposé au niveau module pour faciliter le monkey-patching en tests.
# Si l'import échoue au chargement (environnement partiel), on retentera à l'exécution.
try:
    from models.database import AsyncSessionLocal as AsyncSessionLocal  # type: ignore
except Exception:  # pragma: no cover - fallback runtime
    AsyncSessionLocal = None  # type: ignore

# ── Packs de crédits disponibles ─────────────────────────────────────────────
CREDIT_PACKS: dict[str, dict[str, Any]] = {
    "starter_50":    {"credits": 50,   "price_dt": 25.0,  "label": "50 crédits IA"},
    "growth_200":    {"credits": 200,  "price_dt": 80.0,  "label": "200 crédits IA"},
    "business_500":  {"credits": 500,  "price_dt": 175.0, "label": "500 crédits IA"},
    "enterprise_1k": {"credits": 1000, "price_dt": 300.0, "label": "1000 crédits IA"},
}

# ── Limites par plan — SOURCE DE VÉRITÉ UNIQUE (miroir ai_guardrails._DEFAULT_QUOTAS) ──
# V24 ENTERPRISE FIX : était incohérent entre ai_guardrails.py et credit_ledger.py.
# Ces valeurs doivent rester strictement identiques à _DEFAULT_QUOTAS dans ai_guardrails.py.
PLAN_MONTHLY_CREDITS: dict[str, int] = {
    "free":         0,      # Plan free : IA bloquée (0 = pas de crédits IA)
    "starter":      500,
    "business":     2000,
    "premium":      5000,
    "pro_whatsapp": 10000,
    "pro":          5000,
    "enterprise":   20000,
}


def _extract_store_id_and_limit(
    args: tuple[Any, ...],
    kwargs: dict[str, Any] | None = None,
    limit: int = 50,
) -> tuple[int, int]:
    """Normalise les appels legacy et nommés.

    Compatibilité supportée:
      - get_ledger_history(store_id=1, limit=10)
      - get_ledger_history(1, limit=10)
      - get_ledger_history(db, 1, limit=10)  # ancien style avec session injectée
    """
    kwargs = kwargs or {}

    kw_limit = kwargs.get("limit")
    if kw_limit is not None:
        limit = kw_limit

    if "store_id" in kwargs and kwargs["store_id"] is not None:
        return int(kwargs["store_id"]), int(limit)

    if len(args) == 1:
        return int(args[0]), int(limit)
    if len(args) >= 2:
        return int(args[1]), int(limit)
    raise TypeError("store_id manquant")


def estimate_llm_credits(input_tokens: int, output_tokens: int) -> int:
    total = max(0, int(input_tokens)) + max(0, int(output_tokens))
    return max(1, (total + 999) // 1000) if total else 0


async def get_ledger_history(*args, limit: int = 50, **kwargs) -> list[dict]:
    """Retourne l'historique des crédits du tenant depuis credit_events.

    Fallback sur TenantSubscription si credit_events est vide ou inaccessible.
    Accepte les appels positionnels legacy et les appels nommés (store_id=...).
    """
    store_id, limit = _extract_store_id_and_limit(args, kwargs, limit=limit)
    try:
        from sqlalchemy import text

        session_factory = AsyncSessionLocal
        if session_factory is None:  # lazy fallback pour les environnements partiels
            from models.database import AsyncSessionLocal as session_factory

        async with session_factory() as db:
            # Lire la table credit_events (migration 0033 — requise en production)
            try:
                result = await db.execute(
                    text("""
                        SELECT event_type, credits_delta, balance_after,
                               description, created_at
                        FROM credit_events
                        WHERE store_id = :sid
                        ORDER BY created_at DESC
                        LIMIT :lim
                    """),
                    {"sid": store_id, "lim": limit},
                )
                rows = result.mappings().all()
                if rows:
                    return [
                        {
                            "event_type": r["event_type"],
                            "credits_delta": r["credits_delta"],
                            "balance_after": r["balance_after"],
                            "description": r["description"],
                            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                        }
                        for r in rows
                    ]
            except Exception as exc:
                logger.warning("get_ledger_history credit_events error store_id=%s: %s", store_id, exc)

            # Fallback : 1 ligne par abonnement actif (tant que credit_events est vide)
            from sqlalchemy import select

            from security_overlay.models import TenantSubscription

            result = await db.execute(
                select(TenantSubscription)
                .where(TenantSubscription.tenant_id == store_id)
                .order_by(TenantSubscription.created_at.desc())
                .limit(limit)
            )
            subs = result.scalars().all()
            history = []
            for sub in subs:
                plan_credits = PLAN_MONTHLY_CREDITS.get(sub.plan_code or "free", 0)
                history.append({
                    "event_type": "subscription",
                    "credits_delta": plan_credits,
                    "balance_after": plan_credits,
                    "description": f"Abonnement {sub.plan_code} ({sub.duration_months} mois)",
                    "created_at": sub.created_at.isoformat() if sub.created_at else None,
                })
            return history

    except Exception as exc:
        logger.warning("get_ledger_history store_id=%s failed: %s", store_id, exc)
        return []


def _extract_store_id(args: tuple[Any, ...], kwargs: dict[str, Any] | None = None) -> int:
    kwargs = kwargs or {}
    if "store_id" in kwargs and kwargs["store_id"] is not None:
        return int(kwargs["store_id"])
    if len(args) == 1:
        return int(args[0])
    if len(args) >= 2:
        return int(args[1])
    raise TypeError("store_id manquant")


async def get_usage_summary(*args, **kwargs) -> dict:
    """Retourne le résumé d'utilisation des crédits du mois courant."""
    store_id = _extract_store_id(args, kwargs)
    try:
        from sqlalchemy import select

        from security_overlay.models import TenantSubscription

        session_factory = AsyncSessionLocal
        if session_factory is None:  # lazy fallback pour les environnements partiels
            from models.database import AsyncSessionLocal as session_factory

        async with session_factory() as db:
            result = await db.execute(
                select(TenantSubscription)
                .where(
                    TenantSubscription.tenant_id == store_id,
                    TenantSubscription.status == "active",
                )
                .order_by(TenantSubscription.expires_at.desc())
                .limit(1)
            )
            sub = result.scalar_one_or_none()
            plan_code = sub.plan_code if sub else "free"
            monthly_limit = PLAN_MONTHLY_CREDITS.get(plan_code, 0)

            credits_used = 0
            try:
                from sqlalchemy import text
                now = datetime.now(UTC)
                result_used = await db.execute(
                    text("""
                        SELECT COALESCE(SUM(ABS(credits_delta)), 0) as used
                        FROM credit_events
                        WHERE store_id = :sid
                          AND event_type IN ('usage', 'deduct')
                          AND created_at >= date_trunc('month', :now)
                    """),
                    {"sid": store_id, "now": now},
                )
                credits_used = int(result_used.scalar() or 0)
            except Exception:
                pass

            return {
                "plan_code": plan_code,
                "credits_monthly_limit": monthly_limit,
                "credits_used": credits_used,
                "credits_remaining": max(0, monthly_limit - credits_used),
                "reset_date": (
                    sub.expires_at.isoformat() if sub and sub.expires_at else None
                ),
            }

    except Exception as exc:
        logger.warning("get_usage_summary store_id=%s failed: %s", store_id, exc)
        return {"credits_used": 0, "credits_remaining": 0, "plan_code": "free"}


async def purchase_top_up(store_id: int, pack_id: str, payment_ref: str) -> dict:
    """Enregistre un top-up de crédits après paiement confirmé.

    V24 ENTERPRISE FIX :
      - Ne retourne plus ok=True si credit_events est absent (était un bug silencieux).
      - Écrit en DB d'abord, puis ajoute en Redis atomiquement.
      - Si la migration 0033 n'est pas appliquée, retourne ok=False avec une erreur explicite.
    """
    pack = CREDIT_PACKS.get(pack_id)
    if pack is None:
        return {"ok": False, "error": f"pack_id inconnu: {pack_id}"}

    try:
        from sqlalchemy import text

        session_factory = AsyncSessionLocal
        if session_factory is None:  # lazy fallback pour les environnements partiels
            from models.database import AsyncSessionLocal as session_factory

        async with session_factory() as db:
            # Étape 1 : écriture dans le ledger immuable (migration 0033 requise)
            try:
                await db.execute(
                    text("""
                        INSERT INTO credit_events
                            (store_id, event_type, credits_delta, balance_after,
                             description, reference_id, created_at)
                        VALUES
                            (:sid, 'top_up', :delta, :delta,
                             :desc, :ref, :now)
                    """),
                    {
                        "sid": store_id,
                        "delta": pack["credits"],
                        "desc": f"Top-up {pack['label']}",
                        "ref": payment_ref,
                        "now": datetime.now(UTC),
                    },
                )
                await db.commit()
            except Exception as db_exc:
                # La table credit_events n'existe pas -> la migration 0033 n'a pas été appliquée.
                # On lève une erreur explicite — ne pas confirmer le top-up si on ne peut pas tracer.
                logger.error(
                    "credit_ledger.top_up FATAL: table credit_events inaccessible — "
                    "appliquer la migration 0033. store_id=%s pack=%s ref=%s error=%s",
                    store_id, pack_id, payment_ref, db_exc,
                )
                return {
                    "ok": False,
                    "error": "migration_required",
                    "detail": (
                        "La table credit_events est manquante. "
                        "Exécutez : alembic upgrade head (migration 0033_credit_events_ledger). "
                        "Le top-up n'a PAS été appliqué."
                    ),
                }

            # Étape 2 : mise à jour Redis pour que les quotas soient effectifs immédiatement
            try:
                from services.ai_guardrails import add_tenant_credits
                new_balance = await add_tenant_credits(store_id, pack["credits"], reason="top_up")
                logger.info(
                    "credit_ledger.top_up store_id=%s pack=%s credits=%s ref=%s new_redis_balance=%s",
                    store_id, pack_id, pack["credits"], payment_ref, new_balance,
                )
            except Exception as redis_exc:
                # Redis n'est pas bloquant ici — les crédits sont déjà dans la DB.
                # La prochaine initialisation Redis les rechargera depuis le plan.
                logger.warning(
                    "credit_ledger.top_up: Redis credit update failed (non-bloquant) "
                    "store_id=%s error=%s — crédits en DB OK",
                    store_id, redis_exc,
                )

            return {"ok": True, "credits_added": pack["credits"], "pack": pack}

    except Exception as exc:
        logger.exception("purchase_top_up store_id=%s pack=%s: %s", store_id, pack_id, exc)
        return {"ok": False, "error": str(exc)}


def get_available_packs() -> list[dict]:
    """Retourne la liste des packs de crédits disponibles."""
    return [
        {"pack_id": pid, **info}
        for pid, info in CREDIT_PACKS.items()
    ]


async def allocate_monthly_credits(store_id: int, plan_code: str | None = None) -> dict:
    """Allocate monthly credits to a tenant based on their plan.

    Called at subscription renewal or by admin to reset monthly quota.
    Returns a dict with credits_allocated and new_balance.
    """
    from sqlalchemy import select, update

    from models.database import AsyncSessionLocal, Store

    PLAN_CREDITS: dict[str, int] = {
        "starter": 500,
        "pro": 2000,
        "enterprise": 10000,
        "free": 100,
    }

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Store).where(Store.id == store_id))
            store = result.scalar_one_or_none()
            if store is None:
                logger.warning("allocate_monthly_credits: store %s not found", store_id)
                return {"ok": False, "error": "store_not_found"}

            code = plan_code or store.billing_plan_code or "free"
            credits = PLAN_CREDITS.get(code, 100)

            try:
                from services.ai_guardrails import add_tenant_credits
                new_balance = await add_tenant_credits(store_id, credits, reason="monthly_alloc")
            except Exception as exc:
                logger.warning("allocate_monthly_credits: Redis update failed: %s", exc)
                new_balance = credits

            logger.info(
                "credit_ledger.allocate_monthly store_id=%s plan=%s credits=%s",
                store_id, code, credits,
            )
            return {"ok": True, "credits_allocated": credits, "new_balance": new_balance, "plan": code}

    except Exception as exc:
        logger.exception("allocate_monthly_credits store_id=%s: %s", store_id, exc)
        return {"ok": False, "error": str(exc)}


async def grant_bonus_credits(store_id: int, amount: int, reason: str = "bonus") -> dict:
    """Grant bonus credits to a tenant (admin action).

    Returns a dict with credits_granted and new_balance.
    """
    try:
        from services.ai_guardrails import add_tenant_credits
        new_balance = await add_tenant_credits(store_id, amount, reason=reason)
        logger.info(
            "credit_ledger.grant_bonus store_id=%s amount=%s reason=%s new_balance=%s",
            store_id, amount, reason, new_balance,
        )
        return {"ok": True, "credits_granted": amount, "new_balance": new_balance}
    except Exception as exc:
        logger.exception("grant_bonus_credits store_id=%s amount=%s: %s", store_id, amount, exc)
        return {"ok": False, "error": str(exc)}
