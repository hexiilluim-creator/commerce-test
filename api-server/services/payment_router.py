"""services/payment_router.py — Routage des paiements multi-pays.

Implémentation production :
  - resolve_provider_with_fallback : résout le provider optimal selon le pays
    et la configuration payment_config du store.
  - detect_country_from_phone : détecte le pays depuis le préfixe téléphonique.
  - get_default_currency : mappe un pays vers sa devise principale.
  - route_payment, get_payment_status, handle_payment_callback :
    délèguent au provider résolu via PaymentFactory.

Providers supportés : flouci | konnect | stripe | paypal | cash | cmi | aliapay | nexus | clix | tnpay
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("payment_router")

# ── Mapping pays -> providers triés par priorité ───────────────────────────────
# Le premier provider disponible dans payment_config sera sélectionné.
_COUNTRY_PROVIDER_ORDER: dict[str, tuple[str, ...]] = {
    "TN": ("flouci", "konnect", "clix", "tnpay", "stripe", "cash"),
    "MA": ("cmi", "stripe", "cash"),
    "DZ": ("cib", "aliapay", "stripe", "cash"),
    "FR": ("stripe", "paypal", "cash"),
    "AE": ("stripe", "paypal", "cash"),
    "SA": ("stripe", "cash"),
    "EG": ("stripe", "cash"),
}
_FALLBACK_ORDER: tuple[str, ...] = ("stripe", "paypal", "cash")

# ── Mapping pays -> devise ─────────────────────────────────────────────────────
_COUNTRY_CURRENCY: dict[str, str] = {
    "TN": "TND",
    "MA": "MAD",
    "DZ": "DZD",
    "FR": "EUR",
    "AE": "AED",
    "SA": "SAR",
    "EG": "EGP",
    "US": "USD",
    "GB": "GBP",
}

# ── Préfixes téléphoniques -> pays ─────────────────────────────────────────────
# Triés du plus spécifique (plus long) au plus court pour éviter les faux positifs.
_PHONE_PREFIX_COUNTRY: list[tuple[str, str]] = [
    # Tunisie
    ("+216", "TN"), ("00216", "TN"),
    # Maroc
    ("+212", "MA"), ("00212", "MA"),
    # Algérie
    ("+213", "DZ"), ("00213", "DZ"),
    # France
    ("+33", "FR"), ("0033", "FR"),
    # Émirats
    ("+971", "AE"), ("00971", "AE"),
    # Arabie Saoudite
    ("+966", "SA"), ("00966", "SA"),
    # Égypte
    ("+20", "EG"), ("0020", "EG"),
    # US/Canada
    ("+1", "US"),
    # UK
    ("+44", "GB"), ("0044", "GB"),
]


def detect_country_from_phone(phone: str | None) -> str | None:
    """Détecte le pays depuis un numéro de téléphone international.

    Args:
        phone : Numéro de téléphone (format E.164 avec + ou 00, ou local).

    Returns:
        Code pays ISO 3166-1 alpha-2 (ex: "TN", "FR") ou None si inconnu.

    Examples:
        detect_country_from_phone("+21698765432") -> "TN"
        detect_country_from_phone("0033612345678") -> "FR"
        detect_country_from_phone("0612345678") -> None
    """
    if not phone:
        return None
    normalized = phone.strip().replace(" ", "").replace("-", "")
    for prefix, country in _PHONE_PREFIX_COUNTRY:
        if normalized.startswith(prefix):
            return country
    return None


def get_default_currency(country: str | None) -> str:
    """Retourne la devise par défaut pour un pays.

    Args:
        country : Code pays ISO 3166-1 alpha-2.

    Returns:
        Code devise ISO 4217 (ex: "TND", "EUR"). Défaut : "USD".
    """
    if not country:
        return "USD"
    return _COUNTRY_CURRENCY.get(country.upper(), "USD")


def resolve_provider_with_fallback(
    country: str | None,
    payment_config: dict[str, Any] | None,
) -> str:
    """Résout le meilleur provider disponible selon le pays et la config du store.

    Stratégie :
      1. Parcourt les providers par ordre de priorité pour le pays.
      2. Sélectionne le premier trouvé dans payment_config du store.
      3. Si aucun provider du pays n'est configuré, tente stripe puis cash.

    Args:
        country        : Code pays ISO 3166-1 alpha-2 (ex: "TN").
        payment_config : Dict store.payment_config (clés = noms providers).

    Returns:
        Nom du provider sélectionné (ex: "flouci", "stripe", "cash").

    Raises:
        ValueError : Aucun provider configuré dans payment_config.
    """
    cfg = payment_config or {}

    if not cfg:
        raise ValueError(
            "Aucun provider de paiement configuré pour ce store. "
            "Ajoutez au moins un provider dans les paramètres de paiement."
        )

    # Ordre prioritaire selon le pays
    order = _COUNTRY_PROVIDER_ORDER.get((country or "").upper(), _FALLBACK_ORDER)

    # Cherche le premier provider disponible dans la config
    for provider in order:
        if provider in cfg:
            logger.debug(
                "resolve_provider_with_fallback country=%s selected=%s",
                country, provider,
            )
            return provider

    # Fallback universel : stripe puis cash
    for fallback in _FALLBACK_ORDER:
        if fallback in cfg:
            logger.info(
                "resolve_provider_with_fallback country=%s no_country_match "
                "— using fallback=%s",
                country, fallback,
            )
            return fallback

    # Dernier recours : premier provider de la config quel qu'il soit
    first = next(iter(cfg))
    logger.warning(
        "resolve_provider_with_fallback country=%s no_preferred_provider "
        "— using first_available=%s",
        country, first,
    )
    return first


# ── Délégation PaymentFactory ─────────────────────────────────────────────────

async def route_payment(store_id: int, payment_data: dict[str, Any]) -> dict[str, Any]:
    """Route un paiement vers le provider résolu pour ce store.

    Args:
        store_id     : ID du tenant.
        payment_data : Données du paiement (amount, currency, return_url, …).

    Returns:
        Réponse du provider (payment_url, ref, status).
    """
    try:
        from models.database import AsyncSessionLocal, Store
        from services.payment_factory import PaymentFactory

        async with AsyncSessionLocal() as db:
            store = await db.get(Store, store_id)
            if not store:
                return {"status": "error", "error": f"Store {store_id} introuvable"}

            provider_name = resolve_provider_with_fallback(
                store.country, store.payment_config or {}
            )
            factory = PaymentFactory(store)
            provider = factory.get_provider(provider_name)

            amount = payment_data.get("amount", 0)
            currency = payment_data.get("currency") or get_default_currency(store.country)
            return_url = payment_data.get("return_url", "")

            link_data = await provider.create_payment_link(
                amount=amount,
                currency=currency,
                return_url=return_url,
                order_id=payment_data.get("order_id"),
                description=payment_data.get("description", "Paiement AutoCommerce"),
            )
            return {
                "status": "created",
                "provider": provider_name,
                "payment_url": link_data.get("payment_url", ""),
                "ref": link_data.get("ref", ""),
                "currency": currency,
            }
    except ValueError as exc:
        logger.warning("route_payment store_id=%d value_error: %s", store_id, exc)
        return {"status": "error", "error": str(exc)}
    except Exception as exc:
        logger.error("route_payment store_id=%d error: %s", store_id, exc)
        return {"status": "error", "error": "Erreur interne — réessayez dans quelques instants"}


async def get_payment_status(store_id: int, ref: str) -> dict[str, Any]:
    """Vérifie le statut d'un paiement auprès du provider.

    Args:
        store_id : ID du tenant.
        ref      : Référence de paiement retournée par route_payment.

    Returns:
        dict avec status (pending | paid | failed | refunded), ref, amount.
    """
    try:
        from models.database import AsyncSessionLocal, Store
        from services.payment_factory import PaymentFactory

        async with AsyncSessionLocal() as db:
            store = await db.get(Store, store_id)
            if not store:
                return {"status": "unknown", "ref": ref, "error": "Store introuvable"}

            provider_name = resolve_provider_with_fallback(
                store.country, store.payment_config or {}
            )
            factory = PaymentFactory(store)
            provider = factory.get_provider(provider_name)
            return await provider.verify_payment(ref)
    except Exception as exc:
        logger.error("get_payment_status store_id=%d ref=%s error: %s", store_id, ref, exc)
        return {"status": "unknown", "ref": ref, "error": str(exc)}


async def handle_payment_callback(store_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Traite un callback de paiement entrant (redirection post-paiement ou webhook).

    Args:
        store_id : ID du tenant.
        payload  : Corps du callback (provider-specific).

    Returns:
        dict avec ok (bool), ref, status, store_id.
    """
    try:
        ref = (
            payload.get("ref")
            or payload.get("payment_ref")
            or payload.get("transaction_id")
            or ""
        )
        if not ref:
            logger.warning("handle_payment_callback store_id=%d missing ref in payload", store_id)
            return {"ok": False, "error": "Référence de paiement manquante"}

        status_data = await get_payment_status(store_id, ref)
        is_paid = status_data.get("status") in ("paid", "success", "completed")

        logger.info(
            "handle_payment_callback store_id=%d ref=%s status=%s is_paid=%s",
            store_id, ref, status_data.get("status"), is_paid,
        )
        return {
            "ok": is_paid,
            "ref": ref,
            "status": status_data.get("status", "unknown"),
            "store_id": store_id,
            "amount": status_data.get("amount"),
            "currency": status_data.get("currency"),
        }
    except Exception as exc:
        logger.error("handle_payment_callback store_id=%d error: %s", store_id, exc)
        return {"ok": False, "error": str(exc)}
