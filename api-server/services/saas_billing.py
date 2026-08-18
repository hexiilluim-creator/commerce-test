"""services/saas_billing.py — Facturation SaaS multi-tenant.

Implémentation production complète :
  - Catalogue de plans depuis la table `plan_limits` (migration 0027).
  - Abonnements multi-durée (3/6/12 mois) via `tenant_subscriptions` (migration 0028).
  - Synchronisation Store.billing_plan_code / billing_status après chaque upsert.
  - Checkout Stripe avec metadata tenant (plan, store_id, duration_months).
  - Vérification signature webhook Stripe + upsert abonnement.
  - Helpers SuperAdmin : get_subscription_overview, upsert_subscription,
    expire_overdue_subscriptions, list_plans_catalog.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from security_overlay.models import TenantSubscription
from security_overlay.plan_catalog import assert_plan_activation_allowed

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Catalogue statique de secours (utilisé si plan_limits vide)
# ──────────────────────────────────────────────────────────────────────────────
_FALLBACK_PLANS: list[dict[str, Any]] = [
    {
        "plan_code": "starter",
        "display_name": "Starter",
        "rank": 10,
        "price_monthly_dt": 19.99,
        "price_3months_dt": 59.0,
        "price_6months_dt": 97.0,
        "price_12months_dt": 199.0,
        "monthly_ai_credits": 500,
        "max_products": 50,
        "max_users": 1,
        "whatsapp_enabled": False,
        "included_channels": ["messenger", "instagram", "tiktok"],
    },
    {
        "plan_code": "business",
        "display_name": "Business",
        "rank": 20,
        "price_monthly_dt": 29.99,
        "price_3months_dt": 89.0,
        "price_6months_dt": 145.0,
        "price_12months_dt": 299.0,
        "monthly_ai_credits": 2000,
        "max_products": 500,
        "max_users": 3,
        "whatsapp_enabled": False,
        "included_channels": ["messenger", "instagram", "tiktok"],
    },
    {
        "plan_code": "premium",
        "display_name": "Premium",
        "rank": 30,
        "price_monthly_dt": 39.99,
        "price_3months_dt": 119.0,
        "price_6months_dt": 195.0,
        "price_12months_dt": 399.0,
        "monthly_ai_credits": 5000,
        "max_products": -1,
        "max_users": 10,
        "whatsapp_enabled": False,
        "included_channels": ["messenger", "instagram", "tiktok"],
    },
    {
        "plan_code": "pro_whatsapp",
        "display_name": "Pro WhatsApp",
        "rank": 40,
        "price_monthly_dt": 59.99,
        "price_3months_dt": 179.0,
        "price_6months_dt": 290.0,
        "price_12months_dt": 599.0,
        "monthly_ai_credits": 10000,
        "max_products": -1,
        "max_users": 20,
        "whatsapp_enabled": True,
        "included_channels": ["messenger", "instagram", "tiktok", "whatsapp"],
    },
    # AJOUT (audit) : palier Gold. price_monthly_dt est un PLACEHOLDER à
    # valider côté produit/pricing. NOTE : "enterprise" manquait déjà de
    # cette liste avant cet ajout (gap pré-existant, hors scope de ce fix).
    {
        "plan_code": "gold",
        "display_name": "Gold",
        "rank": 50,
        "price_monthly_dt": 149.99,  # PLACEHOLDER — à valider
        "price_3months_dt": 429.0,
        "price_6months_dt": 699.0,
        "price_12months_dt": 1399.0,
        "monthly_ai_credits": 20000,
        "max_products": -1,
        "max_users": 50,
        "whatsapp_enabled": True,
        "included_channels": ["messenger", "instagram", "tiktok", "whatsapp", "facebook"],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# Catalogue des plans
# ──────────────────────────────────────────────────────────────────────────────


# ── compute_subscription_price — requis par tests/test_saas_billing.py (BLOQUANT B3-B) ──

def compute_subscription_price(plan_code: str, duration_months: int) -> float:
    """Calcule le prix total d'un abonnement selon le plan et la durée.

    Utilise le catalogue statique _FALLBACK_PLANS (pas besoin de DB —
    permet d'être appelé de façon synchrone dans les tests).

    Args:
        plan_code       : ex. "starter", "business", "premium", "pro_whatsapp"
        duration_months : 1, 3, 6 ou 12

    Returns:
        Prix total en DT (float).

    Raises:
        KeyError  : si le plan_code est inconnu.
        ValueError: si duration_months n'est pas 1, 3, 6 ou 12.
    """
    plan_map = {p["plan_code"]: p for p in _FALLBACK_PLANS}

    if plan_code not in plan_map:
        raise KeyError(f"Unknown plan_code: {plan_code!r}")

    plan = plan_map[plan_code]

    price_key_map = {
        1:  "price_monthly_dt",
        3:  "price_3months_dt",
        6:  "price_6months_dt",
        12: "price_12months_dt",
    }

    if duration_months not in price_key_map:
        raise ValueError(
            f"duration_months must be 1, 3, 6 or 12 — got {duration_months}"
        )

    return float(plan[price_key_map[duration_months]])


async def list_plans_catalog(db: AsyncSession) -> list[dict[str, Any]]:
    """Retourne le catalogue des plans actifs depuis plan_limits.

    Fallback sur le catalogue statique si la table est vide ou inaccessible
    (utile en CI ou avant la première migration).
    """
    try:
        from sqlalchemy import text

        result = await db.execute(
            text("SELECT * FROM plan_limits WHERE is_active = true ORDER BY rank ASC")
        )
        rows = result.mappings().all()
        if rows:
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("list_plans_catalog db error (fallback statique): %s", exc)
        # P1.4-FIX : sans ce rollback, une transaction PostgreSQL en échec reste
        # "aborted" pour tout le reste de la session — toute requête suivante sur
        # cette même session (même dans un handler HTTP totalement différent, si
        # la session est réutilisée) échoue avec
        # "current transaction is aborted, commands ignored until end of
        # transaction block", masquant la vraie cause. Diagnostiqué via audit de
        # déploiement (Manus, juillet 2026) sur test_super_admin_stores_pagination.
        await db.rollback()

    return _FALLBACK_PLANS


async def get_plan_by_code(db: AsyncSession, plan_code: str) -> dict[str, Any] | None:
    """Retourne un plan par son code depuis plan_limits."""
    try:
        from sqlalchemy import text

        result = await db.execute(
            text("SELECT * FROM plan_limits WHERE plan_code = :code AND is_active = true"),
            {"code": plan_code},
        )
        row = result.mappings().first()
        if row:
            return dict(row)
    except Exception as exc:
        logger.warning("get_plan_by_code db error: %s", exc)
        # P1.4-FIX : voir le commentaire équivalent dans list_plans_catalog —
        # même bug de transaction empoisonnée, cause racine de l'échec de
        # test_super_admin_stores_pagination diagnostiqué par l'audit Manus.
        await db.rollback()

    # Fallback catalogue statique
    return next((p for p in _FALLBACK_PLANS if p["plan_code"] == plan_code), None)


# ──────────────────────────────────────────────────────────────────────────────
# Abonnements tenant
# ──────────────────────────────────────────────────────────────────────────────

async def get_active_subscription(db: AsyncSession, store_id: int) -> TenantSubscription | None:
    """Retourne l'abonnement actif d'un tenant (le plus récent avec status=active)."""
    result = await db.execute(
        select(TenantSubscription)
        .where(
            TenantSubscription.tenant_id == store_id,
            TenantSubscription.status == "active",
        )
        .order_by(desc(TenantSubscription.expires_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_subscription_overview(db: AsyncSession, store_id: int) -> dict[str, Any]:
    """Retourne un aperçu complet de l'abonnement d'un tenant.

    Appelé par :
      - GET /billing/subscription (tenant)
      - GET /admin/tenants/{id} (SuperAdmin)
      - GET /billing/onboarding (checklist)

    Structure retournée compatible avec le frontend SuperAdmin et les
    endpoints billing (billing_plan_code, status, expires_at, days_remaining, …).
    """
    from models.database import Store

    store = await db.get(Store, store_id)
    if not store:
        return _empty_subscription_overview(store_id)

    active_sub = await get_active_subscription(db, store_id)

    # Détermine le plan_code effectif
    plan_code: str = "free"
    if active_sub and active_sub.status == "active":
        plan_code = active_sub.plan_code
    elif getattr(store, "billing_plan_code", None):
        plan_code = store.billing_plan_code

    plan = await get_plan_by_code(db, plan_code)
    plan_label = (plan or {}).get("display_name", plan_code.capitalize())

    now = datetime.now(UTC)
    expires_at: datetime | None = None
    starts_at: datetime | None = None
    days_remaining: int | None = None
    duration_months: int | None = None
    subscription_status = getattr(store, "billing_status", "free")

    if active_sub:
        expires_at = active_sub.expires_at
        starts_at = active_sub.starts_at
        duration_months = active_sub.duration_months
        subscription_status = active_sub.status

        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if starts_at and starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=UTC)

        if expires_at:
            delta = expires_at - now
            days_remaining = max(0, delta.days)

    return {
        # Champs principaux utilisés par le frontend
        "store_id": store_id,
        "billing_plan_code": plan_code,
        "plan_label": plan_label,
        "status": subscription_status,
        "is_paid": plan_code != "free" and subscription_status == "active",
        # Dates abonnement
        "starts_at": starts_at.isoformat() if starts_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "days_remaining": days_remaining,
        "duration_months": duration_months,
        # Quotas du plan
        "monthly_ai_credits": (plan or {}).get("monthly_ai_credits", 0),
        "max_products": (plan or {}).get("max_products", 50),
        "max_users": (plan or {}).get("max_users", 1),
        "whatsapp_enabled": (plan or {}).get("whatsapp_enabled", False),
        "included_channels": (plan or {}).get("included_channels", []),
        # Détail prix
        "price_monthly_dt": (plan or {}).get("price_monthly_dt", 0.0),
        "price_paid_dt": active_sub.price_paid_dt if active_sub else None,
        # Rappels
        "reminder_7d_sent_at": (
            active_sub.reminder_7d_sent_at.isoformat() if active_sub and active_sub.reminder_7d_sent_at else None
        ),
        "reminder_1d_sent_at": (
            active_sub.reminder_1d_sent_at.isoformat() if active_sub and active_sub.reminder_1d_sent_at else None
        ),
        # ID de l'abonnement courant (pour les updates admin)
        "subscription_id": active_sub.id if active_sub else None,
        "notes": active_sub.notes if active_sub else None,
    }


def _empty_subscription_overview(store_id: int) -> dict[str, Any]:
    return {
        "store_id": store_id,
        "billing_plan_code": "free",
        "plan_label": "Gratuit",
        "status": "free",
        "is_paid": False,
        "starts_at": None,
        "expires_at": None,
        "days_remaining": None,
        "duration_months": None,
        "monthly_ai_credits": 0,
        "max_products": 50,
        "max_users": 1,
        "whatsapp_enabled": False,
        "included_channels": [],
        "price_monthly_dt": 0.0,
        "price_paid_dt": None,
        "reminder_7d_sent_at": None,
        "reminder_1d_sent_at": None,
        "subscription_id": None,
        "notes": None,
    }


async def upsert_subscription(
    db: AsyncSession,
    *,
    tenant_id: int,
    plan_code: str,
    duration_months: int,
    price_paid_dt: float,
    starts_at: datetime,
    expires_at: datetime,
    created_by: str | None = None,
    notes: str | None = None,
    price_paid_usd: float | None = None,
) -> TenantSubscription:
    """Crée ou met à jour l'abonnement actif d'un tenant.

    Stratégie : expire les abonnements actifs existants puis crée un nouvel
    enregistrement. Cette approche préserve l'historique complet des abonnements
    dans la table tenant_subscriptions (append-optimized, nécessaire pour l'audit).

    Synchronise également Store.billing_plan_code et Store.billing_status.

    Args:
        db              : Session SQLAlchemy async.
        tenant_id       : ID du store.
        plan_code       : Code du plan (starter|business|premium|pro_whatsapp).
        duration_months : Durée choisie (3|6|12).
        price_paid_dt   : Prix payé en Dinars Tunisiens.
        starts_at       : Début de la période (UTC-aware).
        expires_at      : Fin de la période (UTC-aware).
        created_by      : Identifiant de l'auteur (admin:email|system|api).
        notes           : Notes libres (raison override, bon de commande, …).
        price_paid_usd  : Équivalent USD indicatif (optionnel).

    Returns:
        TenantSubscription : L'objet ORM du nouvel abonnement.
    """
    now = datetime.now(UTC)

    # Expire les abonnements actifs précédents (historique préservé)
    await db.execute(
        update(TenantSubscription)
        .where(
            TenantSubscription.tenant_id == tenant_id,
            TenantSubscription.status == "active",
        )
        .values(status="superseded", updated_at=now)
    )

    # Normalisation timezone
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    new_sub = TenantSubscription(
        tenant_id=tenant_id,
        plan_code=plan_code,
        duration_months=duration_months,
        price_paid_dt=price_paid_dt,
        price_paid_usd=price_paid_usd,
        starts_at=starts_at,
        expires_at=expires_at,
        status="active",
        created_by=created_by,
        notes=notes,
    )
    db.add(new_sub)
    await db.flush()  # obtenir new_sub.id avant le commit

    # Synchronise Store.billing_plan_code / billing_status
    await _sync_store_billing(db, tenant_id, plan_code, "active")

    logger.info(
        "upsert_subscription tenant_id=%d plan=%s duration=%dm expires=%s created_by=%s",
        tenant_id,
        plan_code,
        duration_months,
        expires_at.isoformat(),
        created_by or "unknown",
    )
    return new_sub


async def _sync_store_billing(
    db: AsyncSession,
    store_id: int,
    plan_code: str,
    billing_status: str,
) -> None:
    """Synchronise les colonnes billing_* sur la table stores."""
    from models.database import Store

    await db.execute(
        update(Store)
        .where(Store.id == store_id)
        .values(billing_plan_code=plan_code, billing_status=billing_status)
    )


# ──────────────────────────────────────────────────────────────────────────────
# Expiration automatique des abonnements
# ──────────────────────────────────────────────────────────────────────────────

async def expire_overdue_subscriptions(db: AsyncSession) -> int:
    """Marque comme 'expired' les abonnements dont la date d'expiration est dépassée.

    À appeler depuis une tâche Celery périodique (toutes les heures recommandé).

    Returns:
        Nombre d'abonnements expirés lors de cette exécution.
    """
    now = datetime.now(UTC)

    result = await db.execute(
        select(TenantSubscription).where(
            TenantSubscription.status == "active",
            TenantSubscription.expires_at < now,
        )
    )
    expired_subs = result.scalars().all()

    count = 0
    for sub in expired_subs:
        sub.status = "expired"
        sub.blocked_at = now
        await _sync_store_billing(db, sub.tenant_id, sub.plan_code, "expired")
        count += 1

    if count:
        await db.flush()
        logger.info("expire_overdue_subscriptions expired_count=%d", count)

    return count


# ──────────────────────────────────────────────────────────────────────────────
# Stripe Checkout
# ──────────────────────────────────────────────────────────────────────────────

async def create_stripe_checkout_session(
    db: AsyncSession,
    tenant_id: int,
    plan_code: str,
    success_url: str,
    cancel_url: str,
    duration_months: int = 1,
) -> str:
    """Crée une session Stripe Checkout et retourne l'URL de paiement.

    Args:
        db             : Session SQLAlchemy async.
        tenant_id      : ID du store.
        plan_code      : Code du plan cible.
        success_url    : URL de redirection après paiement réussi.
        cancel_url     : URL de redirection en cas d'annulation.
        duration_months: Durée de l'abonnement (1|3|6|12).

    Returns:
        URL de checkout Stripe.

    Raises:
        ValueError : plan_code inconnu ou STRIPE_SECRET_KEY non configuré.
        RuntimeError: Erreur Stripe inattendue.
    """
    try:
        import stripe  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "Le package 'stripe' n'est pas installé. Ajoutez stripe>=8.0.0 aux dépendances."
        ) from exc

    from config import settings as cfg

    if not getattr(cfg, "STRIPE_SECRET_KEY", ""):
        raise ValueError(
            "STRIPE_SECRET_KEY non configuré. Définissez la variable d'environnement avant "
            "d'activer le checkout Stripe."
        )

    plan = await get_plan_by_code(db, plan_code)
    if not plan:
        raise ValueError(f"Plan inconnu : {plan_code!r}")
    assert_plan_activation_allowed(plan_code)

    # Calcul du prix selon la durée
    duration_price_map = {
        1: plan.get("price_monthly_dt", 0.0),
        3: plan.get("price_3months_dt", plan.get("price_monthly_dt", 0.0) * 3),
        6: plan.get("price_6months_dt", plan.get("price_monthly_dt", 0.0) * 6 * 0.9),
        12: plan.get("price_12months_dt", plan.get("price_annual_dt", plan.get("price_monthly_dt", 0.0) * 10)),
    }
    price_dt = duration_price_map.get(duration_months, plan.get("price_monthly_dt", 0.0))
    price_usd = plan.get("price_monthly_usd", 0.0) * duration_months

    stripe.api_key = cfg.STRIPE_SECRET_KEY

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": f"AutoCommerce {plan['display_name']} — {duration_months} mois",
                            "description": (
                                f"{plan.get('monthly_ai_credits', 0):,} crédits IA/mois · "
                                f"{plan.get('max_products', 50)} produits max"
                            ),
                        },
                        "unit_amount": int(price_usd * 100),  # cents
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "store_id": str(tenant_id),
                "plan_code": plan_code,
                "duration_months": str(duration_months),
                "price_dt": str(price_dt),
            },
            expires_at=int(
                (datetime.now(UTC) + timedelta(hours=2)).timestamp()
            ),
        )
        logger.info(
            "stripe_checkout_created store_id=%d plan=%s duration=%dm session_id=%s",
            tenant_id,
            plan_code,
            duration_months,
            session.id,
        )
        return session.url or ""
    except stripe.StripeError as exc:
        logger.error("stripe_checkout_error store_id=%d plan=%s error=%s", tenant_id, plan_code, exc)
        raise RuntimeError(f"Stripe error: {exc}") from exc


# ──────────────────────────────────────────────────────────────────────────────
# Stripe Webhook
# ──────────────────────────────────────────────────────────────────────────────

async def handle_stripe_webhook(
    db: AsyncSession,
    payload: bytes,
    stripe_signature: str,
) -> None:
    """Traite un événement webhook Stripe.

    Vérifie la signature HMAC Stripe, puis traite les événements :
      - checkout.session.completed  -> upsert abonnement
      - payment_intent.succeeded    -> log confirmé
      - payment_intent.payment_failed -> log échec

    Args:
        db               : Session SQLAlchemy async.
        payload          : Corps brut de la requête HTTP.
        stripe_signature : Header Stripe-Signature.

    Raises:
        ValueError : Signature invalide ou payload malformé.
    """
    try:
        import stripe  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("Package 'stripe' non installé.") from exc

    from config import settings as cfg

    webhook_secret = getattr(cfg, "STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        raise ValueError(
            "STRIPE_WEBHOOK_SECRET non configuré. "
            "Définissez la variable d'environnement pour sécuriser les webhooks."
        )

    stripe.api_key = getattr(cfg, "STRIPE_SECRET_KEY", "")

    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, webhook_secret)
    except stripe.SignatureVerificationError as exc:
        logger.warning("stripe_webhook signature_invalid: %s", exc)
        raise ValueError(f"Signature Stripe invalide : {exc}") from exc
    except Exception as exc:
        logger.error("stripe_webhook parse_error: %s", exc)
        raise ValueError(f"Payload webhook malformé : {exc}") from exc

    event_type = event["type"]
    logger.info("stripe_webhook event=%s", event_type)

    if event_type == "checkout.session.completed":
        session_obj = event["data"]["object"]
        metadata = session_obj.get("metadata", {})
        store_id = int(metadata.get("store_id", 0))
        plan_code = metadata.get("plan_code", "starter")
        duration_months = int(metadata.get("duration_months", 1))
        price_dt = float(metadata.get("price_dt", 0.0))

        if not store_id:
            logger.error("stripe_webhook checkout.session.completed missing store_id in metadata")
            return

        now = datetime.now(UTC)
        expires_at = now + timedelta(days=30 * duration_months)

        await upsert_subscription(
            db,
            tenant_id=store_id,
            plan_code=plan_code,
            duration_months=duration_months,
            price_paid_dt=price_dt,
            starts_at=now,
            expires_at=expires_at,
            created_by=f"stripe:webhook:{session_obj.get('id', 'unknown')}",
            notes=f"Stripe checkout session {session_obj.get('id', '')}",
        )
        await db.commit()
        logger.info(
            "stripe_webhook subscription_activated store_id=%d plan=%s duration=%dm",
            store_id,
            plan_code,
            duration_months,
        )

    elif event_type in ("payment_intent.succeeded", "payment_intent.payment_failed"):
        pi = event["data"]["object"]
        logger.info(
            "stripe_webhook %s payment_intent_id=%s amount=%s currency=%s",
            event_type,
            pi.get("id"),
            pi.get("amount"),
            pi.get("currency"),
        )

    else:
        logger.debug("stripe_webhook unhandled event_type=%s", event_type)


# ──────────────────────────────────────────────────────────────────────────────
# Flouci Checkout (marché Tunisie/local — virement/carte via Flouci)
# ──────────────────────────────────────────────────────────────────────────────
# NOTE IMPORTANTE : cette intégration a été écrite sans accès à un compte
# Flouci réel (sandbox ou production) — elle reproduit fidèlement le contrat
# d'API déjà implémenté et fonctionnel dans services/payment_factory.py
# (FlouciProvider, utilisé pour les paiements de commandes e-commerce), mais
# le format exact du payload webhook Flouci pour un paiement d'ABONNEMENT n'a
# pas pu être vérifié en conditions réelles. Avant mise en production :
# déclencher un vrai paiement en sandbox Flouci et confirmer que le champ
# `developer_tracking_id` qu'on leur envoie est bien celui qu'ils renvoient
# dans le webhook (voir _extract_flouci_tracking_id ci-dessous) — sinon
# ajuster le parsing selon le payload réel observé.

def _build_flouci_tracking_id(tenant_id: int, plan_code: str, duration_months: int) -> str:
    """Encode store_id/plan_code/duration dans le tracking_id envoyé à Flouci.

    Flouci n'offre pas d'équivalent au `metadata` dict de Stripe — on encode
    donc directement l'information nécessaire dans le tracking_id, que Flouci
    doit nous renvoyer tel quel dans son webhook (developer_tracking_id).
    """
    import secrets as _secrets

    return f"sub-{tenant_id}-{plan_code}-{duration_months}-{_secrets.token_hex(4)}"


def _parse_flouci_tracking_id(tracking_id: str) -> tuple[int, str, int] | None:
    """Décode le tracking_id — inverse de _build_flouci_tracking_id."""
    parts = (tracking_id or "").split("-")
    if len(parts) != 5 or parts[0] != "sub":
        return None
    try:
        return int(parts[1]), parts[2], int(parts[3])
    except ValueError:
        return None


async def create_flouci_payment(
    db: AsyncSession,
    tenant_id: int,
    plan_code: str,
    success_url: str,
    fail_url: str,
    duration_months: int = 1,
) -> str:
    """Crée un paiement Flouci et retourne l'URL de paiement.

    Args:
        db             : Session SQLAlchemy async.
        tenant_id      : ID du store.
        plan_code      : Code du plan cible.
        success_url    : URL de redirection après paiement réussi.
        fail_url       : URL de redirection en cas d'échec/annulation.
        duration_months: Durée de l'abonnement (1|3|6|12).

    Returns:
        URL de paiement Flouci (à rediriger le marchand vers cette URL).

    Raises:
        ValueError : plan_code inconnu ou FLOUCI_APP_TOKEN/SECRET non configurés.
    """
    from config import settings as cfg
    from services.payment_factory import PaymentFactory

    if not getattr(cfg, "FLOUCI_APP_TOKEN", "") or not getattr(cfg, "FLOUCI_APP_SECRET", ""):
        raise ValueError(
            "FLOUCI_APP_TOKEN/FLOUCI_APP_SECRET non configurés. Définissez ces variables "
            "d'environnement avant d'activer le paiement Flouci pour les abonnements."
        )

    plan = await get_plan_by_code(db, plan_code)
    if not plan:
        raise ValueError(f"Plan inconnu : {plan_code!r}")
    assert_plan_activation_allowed(plan_code)

    duration_price_map = {
        1: plan.get("price_monthly_dt", 0.0),
        3: plan.get("price_3months_dt", plan.get("price_monthly_dt", 0.0) * 3),
        6: plan.get("price_6months_dt", plan.get("price_monthly_dt", 0.0) * 6 * 0.9),
        12: plan.get("price_12months_dt", plan.get("price_annual_dt", plan.get("price_monthly_dt", 0.0) * 10)),
    }
    price_dt = duration_price_map.get(duration_months, plan.get("price_monthly_dt", 0.0))

    provider = PaymentFactory.get(
        "flouci",
        cfg={"app_token": cfg.FLOUCI_APP_TOKEN, "app_secret": cfg.FLOUCI_APP_SECRET},
    )
    tracking_id = _build_flouci_tracking_id(tenant_id, plan_code, duration_months)

    result = await provider.create_payment_link(
        amount=price_dt,
        currency="TND",
        description=f"AutoCommerce {plan['display_name']} — {duration_months} mois",
        reference=tracking_id,
        success_url=success_url,
        fail_url=fail_url,
    )
    logger.info(
        "flouci_checkout_created store_id=%d plan=%s duration=%dm tracking_id=%s",
        tenant_id, plan_code, duration_months, tracking_id,
    )
    return result["url"]


async def handle_flouci_webhook(db: AsyncSession, payload: bytes, headers: dict[str, str]) -> None:
    """Traite un événement webhook Flouci pour l'activation d'abonnement.

    Vérifie la signature, extrait le tracking_id, revérifie le statut auprès
    de Flouci (defense in depth — ne fait jamais confiance au seul contenu du
    webhook), puis active l'abonnement via upsert_subscription si payé.

    Args:
        db      : Session SQLAlchemy async.
        payload : Corps brut de la requête HTTP.
        headers : Headers HTTP (pour vérification de signature).

    Raises:
        ValueError : Signature invalide, payload malformé, ou tracking_id
            non reconnu.
    """
    import json

    from config import settings as cfg
    from services.payment_factory import PaymentFactory

    provider = PaymentFactory.get(
        "flouci",
        cfg={
            "app_token": cfg.FLOUCI_APP_TOKEN,
            "app_secret": cfg.FLOUCI_APP_SECRET,
            "webhook_secret": getattr(cfg, "FLOUCI_WEBHOOK_SECRET", ""),
        },
    )
    is_valid, reason = provider.verify_webhook_signature(
        payload, {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    )
    if not is_valid:
        logger.warning("flouci_webhook signature_invalid: %s", reason)
        raise ValueError(f"Signature Flouci invalide : {reason}")

    try:
        event = json.loads(payload)
    except Exception as exc:
        logger.error("flouci_webhook parse_error: %s", exc)
        raise ValueError(f"Payload webhook Flouci malformé : {exc}") from exc

    # NOTE : nom de champ à confirmer contre un vrai payload Flouci (voir note
    # en tête de section) — on essaie les variantes les plus probables.
    tracking_id = (
        event.get("developer_tracking_id")
        or event.get("result", {}).get("developer_tracking_id")
        or event.get("tracking_id")
        or ""
    )
    payment_id = event.get("payment_id") or event.get("result", {}).get("payment_id") or ""

    parsed = _parse_flouci_tracking_id(tracking_id)
    if not parsed:
        logger.error("flouci_webhook tracking_id non reconnu: %r", tracking_id)
        return
    store_id, plan_code, duration_months = parsed

    # Defense in depth : ne jamais activer sur la seule foi du contenu du
    # webhook — revérifier le statut réel auprès de Flouci (même pattern que
    # payment_link_ai_tool.py pour les paiements de commandes).
    verify_result = await provider.verify_payment(payment_id) if payment_id else {"status": "unknown"}
    if verify_result.get("status") not in ("success", "successful", "paid", "completed"):
        logger.info(
            "flouci_webhook payment_not_confirmed store_id=%d status=%s",
            store_id, verify_result.get("status"),
        )
        return

    plan = await get_plan_by_code(db, plan_code)
    price_dt = (plan or {}).get("price_monthly_dt", 0.0) * duration_months

    now = datetime.now(UTC)
    expires_at = now + timedelta(days=30 * duration_months)

    await upsert_subscription(
        db,
        tenant_id=store_id,
        plan_code=plan_code,
        duration_months=duration_months,
        price_paid_dt=price_dt,
        starts_at=now,
        expires_at=expires_at,
        created_by=f"flouci:webhook:{payment_id or tracking_id}",
        notes=f"Flouci payment_id={payment_id} tracking_id={tracking_id}",
    )
    await db.commit()
    logger.info(
        "flouci_webhook subscription_activated store_id=%d plan=%s duration=%dm",
        store_id, plan_code, duration_months,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Seed / initialisation
# ──────────────────────────────────────────────────────────────────────────────

async def ensure_default_saas_plans(db: AsyncSession) -> None:
    """S'assure que la table plan_limits contient au moins les 4 plans de base.

    Appelé depuis le script de setup (setup_final.py) et le startup de l'API.
    Idempotent — ne crée que les plans manquants.
    """
    try:
        from sqlalchemy import text

        result = await db.execute(text("SELECT COUNT(*) FROM plan_limits"))
        count = result.scalar() or 0
        if count >= 4:
            logger.info("ensure_default_saas_plans plan_limits already seeded count=%d", count)
            return

        logger.info("ensure_default_saas_plans seeding %d default plans", len(_FALLBACK_PLANS))
        # P1.5-FIX : `::jsonb` est une syntaxe de cast propre à PostgreSQL — sur
        # SQLite (tests/dev), le driver échoue à parser le paramètre nommé suivi
        # de ce cast (mismatch de nombre de bindings), et l'INSERT entier échouait
        # silencieusement (capturé par le except plus bas, jamais remonté). Vérifié
        # par un test direct : sans ce fix, la table plan_limits reste vide sur
        # SQLite et toute lecture retombe silencieusement sur _FALLBACK_PLANS,
        # masquant le problème au lieu de le révéler.
        is_postgres = db.bind.dialect.name == "postgresql"
        included_channels_expr = ":included_channels::jsonb" if is_postgres else ":included_channels"
        for plan in _FALLBACK_PLANS:
            await db.execute(
                text(f"""
                    INSERT INTO plan_limits (
                        plan_code, display_name, rank,
                        price_monthly_dt, price_monthly_usd,
                        price_3months_dt, price_6months_dt, price_12months_dt,
                        price_annual_dt, price_annual_usd,
                        max_products, max_users, monthly_ai_credits,
                        whatsapp_enabled, included_channels, is_active
                    ) VALUES (
                        :plan_code, :display_name, :rank,
                        :price_monthly_dt, 0,
                        :price_3months_dt, :price_6months_dt, :price_12months_dt,
                        :price_12months_dt, 0,
                        :max_products, :max_users, :monthly_ai_credits,
                        :whatsapp_enabled, {included_channels_expr}, true
                    )
                    ON CONFLICT (plan_code) DO NOTHING
                """),
                {
                    "plan_code": plan["plan_code"],
                    "display_name": plan["display_name"],
                    "rank": plan["rank"],
                    "price_monthly_dt": plan["price_monthly_dt"],
                    "price_3months_dt": plan["price_3months_dt"],
                    "price_6months_dt": plan["price_6months_dt"],
                    "price_12months_dt": plan["price_12months_dt"],
                    "max_products": plan["max_products"],
                    "max_users": plan["max_users"],
                    "monthly_ai_credits": plan["monthly_ai_credits"],
                    "whatsapp_enabled": plan["whatsapp_enabled"],
                    "included_channels": json.dumps(plan["included_channels"]),
                },
            )
        await db.commit()
        logger.info("ensure_default_saas_plans seeding complete")
    except Exception as exc:
        logger.error("ensure_default_saas_plans error: %s", exc)
        # P1.4-FIX : même bug de transaction empoisonnée que list_plans_catalog/
        # get_plan_by_code — sans rollback, une session réutilisée après cette
        # erreur de seeding au démarrage resterait bloquée en transaction "aborted".
        await db.rollback()
