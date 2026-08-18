"""security_overlay/plan_catalog.py — Catalogue des plans SaaS et packs de crédits.

Source de vérité pour les codes de plan, les prix et les packs de top-up.
Doit rester synchronisé avec :
  - security_overlay/billing_overlay.py (_PLAN_FEATURES)
  - services/saas_billing.py (_FALLBACK_PLANS)
  - La table plan_limits en base de données
"""
from __future__ import annotations

import os

from .models import CreditTopUpPack, SaaSPlan


def is_gold_plan_activation_allowed() -> bool:
    """Retourne True si le plan Gold peut être activé (facturé réellement).

    AUDIT FIX : le commentaire près de la définition du plan "gold" ci-dessous
    annonçait "Activer via: GOLD_PLAN_PUBLIC=true" mais cette variable
    n'était jamais lue nulle part dans le code — is_public=False n'était lui
    non plus vérifié par aucun endpoint réel (list_plans_catalog() dans
    services/saas_billing.py lit la table DB plan_limits, pas ce champ). Le
    prix 149.99 DT est un PLACEHOLDER non validé commercialement ; cette
    fonction doit être appelée avant toute activation RÉELLE (Super Admin
    manuel, checkout Stripe, checkout Flouci) pour empêcher de facturer ce
    montant par accident avant validation business.
    """
    return os.getenv("GOLD_PLAN_PUBLIC", "false").lower() in ("1", "true", "yes")


def assert_plan_activation_allowed(plan_code: str) -> None:
    """Lève ValueError si ce plan ne doit pas encore être activé en réel."""
    if plan_code == "gold" and not is_gold_plan_activation_allowed():
        raise ValueError(
            "Le plan 'gold' a un prix PLACEHOLDER (149.99 DT) non validé "
            "commercialement — activation bloquée. Définissez "
            "GOLD_PLAN_PUBLIC=true une fois le prix confirmé."
        )


PLAN_CATALOG: dict[str, SaaSPlan] = {
    "free": SaaSPlan(
        code="free",
        name="Gratuit",
        price_monthly=0.0,
        features=[],
    ),
    "starter": SaaSPlan(
        code="starter",
        name="Starter",
        price_monthly=19.99,
        features=["channels.messenger", "channels.instagram", "channels.tiktok", "crm.basic", "tax"],
    ),
    "business": SaaSPlan(
        code="business",
        name="Business",
        price_monthly=29.99,
        features=["channels.messenger", "channels.instagram", "channels.tiktok",
                  "crm.basic", "crm.advanced", "auto_followup", "advanced_stats", "tax"],
    ),
    "premium": SaaSPlan(
        code="premium",
        name="Premium",
        price_monthly=39.99,
        features=["channels.messenger", "channels.instagram", "channels.tiktok",
                  "crm.basic", "crm.advanced", "marketing", "auto_followup",
                  "advanced_stats", "tax"],
    ),
    "pro_whatsapp": SaaSPlan(
        code="pro_whatsapp",
        name="Pro WhatsApp",
        price_monthly=59.99,  # FIX: aligned with migration 0027 + saas_billing.py
        features=["channels.whatsapp", "channels.messenger", "channels.instagram",
                  "channels.tiktok", "crm.basic", "crm.advanced", "marketing",
                  "omnichannel", "auto_followup", "advanced_stats", "priority_support", "tax"],
    ),
    # Alias legacy — ne plus utiliser pour les nouvelles souscriptions
    "pro": SaaSPlan(
        code="pro",
        name="Pro (legacy)",
        price_monthly=49.99,
        features=["channels.whatsapp", "channels.instagram", "channels.facebook",
                  "channels.tiktok", "crm.basic", "crm.advanced", "marketing", "tax"],
    ),
    "enterprise": SaaSPlan(
        code="enterprise",
        name="Enterprise",
        price_monthly=99.99,
        features=["channels.whatsapp", "channels.messenger", "channels.instagram", "channels.facebook",
                  "channels.tiktok", "crm.basic", "crm.advanced", "marketing",
                  "omnichannel", "auto_followup", "advanced_stats", "priority_support",
                  "promotions", "loyalty_ia", "visual_builder", "restocking", "b2b_portal", "tax"],
    ),
    # FIX V25 Enterprise: les modules avancés font désormais partie du bundle
    # Enterprise livré au client. Le plan Gold est conservé comme sur-couche
    # commerciale/alias interne, mais n'est plus requis pour utiliser ces pages.
    # ⚠️  PRIX PLACEHOLDER (149.99 DT) — NE PAS ACTIVER EN PRODUCTION
    #     sans validation commerciale. Le plan est marqué is_public=False
    #     pour ne pas apparaître dans /api/v1/billing/plans côté client.
    #     Activer via: GOLD_PLAN_PUBLIC=true dans les variables d'env du store.
    "gold": SaaSPlan(
        code="gold",
        name="Gold",
        price_monthly=149.99,  # PLACEHOLDER — à valider avant activation
        is_public=False,       # Caché des listes publiques jusqu'à validation
        features=["channels.whatsapp", "channels.instagram", "channels.facebook",
                  "channels.tiktok", "crm.basic", "crm.advanced", "marketing",
                  "omnichannel", "auto_followup", "advanced_stats", "priority_support",
                  "promotions", "loyalty_ia", "visual_builder", "restocking", "b2b_portal", "tax"],
    ),
}

CREDIT_TOP_UP_PACKS: list[CreditTopUpPack] = [
    CreditTopUpPack(pack_id="starter_50",    credits=50,   price=25.0,  currency="TND"),
    CreditTopUpPack(pack_id="growth_200",    credits=200,  price=80.0,  currency="TND"),
    CreditTopUpPack(pack_id="business_500",  credits=500,  price=175.0, currency="TND"),
    CreditTopUpPack(pack_id="enterprise_1k", credits=1000, price=300.0, currency="TND"),
]

DURATION_OPTIONS: list[str] = ["monthly", "3months", "6months", "12months"]

_DURATION_DISCOUNTS: dict[str, float] = {
    "monthly":   1.0,
    "3months":   0.92,   # ~8% de réduction
    "6months":   0.85,   # ~15% de réduction
    "12months":  0.78,   # ~22% de réduction
}


def get_plan_spec(plan_code: str) -> SaaSPlan | None:
    """Retourne la spec du plan ou None si le code est inconnu."""
    return PLAN_CATALOG.get(plan_code)


def get_price_for_duration(plan_code: str, duration: str) -> float:
    """Calcule le prix total pour une durée donnée (en dinars tunisiens).

    Args:
        plan_code : Code du plan (ex: "business").
        duration  : Durée parmi monthly | 3months | 6months | 12months.

    Returns:
        Prix total en DT, arrondi à 2 décimales. 0.0 si plan inconnu.
    """
    plan = PLAN_CATALOG.get(plan_code)
    if not plan:
        return 0.0
    months = {"monthly": 1, "3months": 3, "6months": 6, "12months": 12}.get(duration, 1)
    discount = _DURATION_DISCOUNTS.get(duration, 1.0)
    return round(plan.price_monthly * months * discount, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# Tarification EUROPE (EUR) — Distinct du marché MENA/Maghreb
# Positionnement: 5-8x vs MENA pour refléter pouvoir d'achat EU + conformité RGPD
# Usage: get_plan_catalog_for_currency("EUR") depuis l'API billing
# ═══════════════════════════════════════════════════════════════════════════════

PLAN_CATALOG_EUR: dict[str, SaaSPlan] = {
    "starter_eur": SaaSPlan(
        code="starter_eur", name="Starter",
        price_monthly=29.0,
        features=["channels.messenger", "channels.instagram", "channels.tiktok", "crm.basic", "tax"],
    ),
    "business_eur": SaaSPlan(
        code="business_eur", name="Business",
        price_monthly=59.0,
        features=["channels.messenger", "channels.instagram", "channels.tiktok",
                  "crm.basic", "crm.advanced", "auto_followup", "advanced_stats", "tax"],
    ),
    "premium_eur": SaaSPlan(
        code="premium_eur", name="Premium",
        price_monthly=99.0,
        features=["channels.messenger", "channels.instagram", "channels.tiktok",
                  "crm.basic", "crm.advanced", "marketing", "auto_followup", "advanced_stats"],
    ),
    "pro_whatsapp_eur": SaaSPlan(
        code="pro_whatsapp_eur", name="Pro WhatsApp",
        price_monthly=149.0,
        features=["channels.whatsapp", "channels.messenger", "channels.instagram",
                  "channels.tiktok", "crm.basic", "crm.advanced", "marketing",
                  "omnichannel", "auto_followup", "advanced_stats", "priority_support"],
    ),
    "enterprise_eur": SaaSPlan(
        code="enterprise_eur", name="Enterprise",
        price_monthly=299.0,
        features=["channels.whatsapp", "channels.messenger", "channels.instagram",
                  "channels.tiktok", "crm.basic", "crm.advanced", "marketing",
                  "omnichannel", "auto_followup", "advanced_stats",
                  "priority_support", "sla_99_9", "dedicated_csm"],
    ),
}

CREDIT_TOP_UP_PACKS_EUR: list[CreditTopUpPack] = [
    CreditTopUpPack(pack_id="starter_50_eur",    credits=50,   price=15.0,  currency="EUR"),
    CreditTopUpPack(pack_id="growth_200_eur",    credits=200,  price=49.0,  currency="EUR"),
    CreditTopUpPack(pack_id="business_500_eur",  credits=500,  price=99.0,  currency="EUR"),
    CreditTopUpPack(pack_id="enterprise_1k_eur", credits=1000, price=179.0, currency="EUR"),
]


def get_plan_catalog_for_currency(currency: str = "TND") -> dict:
    """Retourne le bon catalogue selon la devise du tenant.

    - TND / MAD / DZD / AED → MENA catalog (DT)
    - EUR / GBP / USD → European catalog (EUR)
    """
    if currency.upper() in ("EUR", "GBP", "USD"):
        return PLAN_CATALOG_EUR
    return PLAN_CATALOG


def get_top_up_packs_for_currency(currency: str = "TND") -> list:
    if currency.upper() in ("EUR", "GBP", "USD"):
        return CREDIT_TOP_UP_PACKS_EUR
    return CREDIT_TOP_UP_PACKS
