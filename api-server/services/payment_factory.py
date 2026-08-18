"""services/payment_factory.py — Factory des passerelles de paiement.

Sélectionne et instancie le bon adaptateur de paiement selon :
  1. la configuration `Store.payment_config` (si un Store est fourni)
  2. le pays `Store.country` (routage par défaut)
  3. la disponibilité des secrets déchiffrés via `settings.decrypt()`.

Providers supportés :
  • flouci   — Tunisie (DTOnline / Flouci Pay)
  • konnect  — Tunisie (Konnect Network)
  • stripe   — international (USD/EUR)
  • cash     — paiement à la livraison (toujours disponible, sans secrets)

Sécurité :
  • Les secrets (`app_token`, `app_secret`, `api_key`, `secret_key`) sont stockés
    dans `Store.payment_config` chiffrés avec le préfixe `enc_` et déchiffrés via
    `settings.decrypt()` au moment de l'usage. Ils ne sont **jamais loggés**.
  • Toutes les erreurs HTTP/réseau sont capturées et converties en `HTTPException`
    503 avec un message générique. Aucun stack-trace côté client.
  • Timeout httpx fixe à 15 s, retry × 2 sur erreurs réseau transitoires.

Compat backward :
  • `PaymentFactory.get(provider_name, cfg)` — utilisé par `api/v1/payment_links.py`.
  • `PaymentFactory.get_provider(store_id, db)` — interface tenant-aware (charge
     le Store, résout le provider par défaut).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.database import Store

logger = logging.getLogger(__name__)

# ── Constantes ───────────────────────────────────────────────────────────────
HTTP_TIMEOUT_SECONDS = 15.0
NETWORK_RETRY_COUNT = 2  # 2 retries = 3 tentatives au total
RETRY_BACKOFF_SECONDS = 0.5

# Mapping pays -> provider par défaut (utilisé uniquement si `payment_config`
# ne précise pas explicitement un provider).
COUNTRY_DEFAULT_PROVIDER: dict[str, tuple[str, ...]] = {
    "TN": ("flouci", "konnect", "stripe", "cash"),
    "MA": ("stripe", "cash"),
    "FR": ("stripe", "cash"),
    "DZ": ("stripe", "cash"),
    "AE": ("stripe", "cash"),
}
FALLBACK_PROVIDER_ORDER: tuple[str, ...] = ("stripe", "cash")


# ══════════════════════════════════════════════════════════════════════════════
# Helpers de configuration
# ══════════════════════════════════════════════════════════════════════════════

def _decrypt_config(raw_cfg: dict[str, Any]) -> dict[str, Any]:
    """Déchiffre les champs `enc_*` d'une config provider.

    Tout champ commençant par `"enc_"` (préfixe convention) voit sa valeur passée
    à `settings.decrypt()`. Les autres champs sont conservés tels quels.

    Lève HTTPException(503) si un champ chiffré est corrompu (la valeur du secret
    ne fuit jamais dans le log).
    """
    if not isinstance(raw_cfg, dict):
        raise HTTPException(status_code=503, detail="payment_config invalide")

    decrypted: dict[str, Any] = {}
    for key, value in raw_cfg.items():
        if isinstance(value, str) and value.startswith("enc_"):
            try:
                decrypted[key] = settings.decrypt(value[4:])
            except Exception:  # noqa: BLE001 — on log et on convertit, secret jamais loggé
                logger.error(
                    "payment_factory: déchiffrement échoué pour le champ '%s' (secret masqué)",
                    key,
                )
                raise HTTPException(
                    status_code=503,
                    detail="Configuration de paiement corrompue — contactez le support",
                )
        else:
            decrypted[key] = value
    return decrypted


def _resolve_provider_name(country: str | None, payment_config: dict[str, Any] | None) -> str:
    """Détermine quel provider utiliser pour un store donné.

    Règles :
      1. Si `payment_config` contient un provider du pays, on le prend (priorité au pays).
      2. Sinon, fallback sur stripe puis cash si configurés.
      3. Sinon, cash (toujours disponible — sans config).
    """
    cfg = payment_config or {}
    country_code = (country or "").upper()

    preferred = COUNTRY_DEFAULT_PROVIDER.get(country_code, FALLBACK_PROVIDER_ORDER)
    for provider in preferred:
        if provider == "cash":
            # Cash est toujours disponible — même sans config.
            return "cash"
        if provider in cfg and cfg[provider]:
            return provider

    # Aucun provider configuré -> cash (paiement à la livraison)
    return "cash"


# ══════════════════════════════════════════════════════════════════════════════
# Providers concrets
# ══════════════════════════════════════════════════════════════════════════════

class _BaseProvider:
    """Interface commune à tous les providers."""

    name: str = "base"

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}

    async def create_payment_link(
        self,
        amount: float,
        currency: str,
        description: str | None = None,
        reference: str | None = None,
        customer_phone: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def verify_payment(self, payment_ref: str, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

    async def refund_payment(self, payment_ref: str, amount: float | None = None, **kwargs: Any) -> dict[str, Any]:
        return {"status": "manual_required", "provider": self.name, "payment_ref": payment_ref, "amount": amount}

    async def cancel_payment(self, payment_ref: str, **kwargs: Any) -> dict[str, Any]:
        return {"status": "manual_required", "provider": self.name, "payment_ref": payment_ref}

    def verify_webhook_signature(self, payload: bytes, headers: dict[str, str], **kwargs: Any) -> tuple[bool, str]:
        return True, "not_applicable"


async def _http_request_with_retry(
    method: str,
    url: str,
    *,
    json_payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    provider_name: str,
) -> httpx.Response:
    """Helper : exécute un appel HTTP avec timeout 15s et retry × 2 sur erreur réseau.

    Aucun secret n'est loggé — uniquement le code HTTP et le nom du provider.
    """
    last_exc: Exception | None = None
    for attempt in range(NETWORK_RETRY_COUNT + 1):
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                response = await client.request(
                    method,
                    url,
                    json=json_payload,
                    headers=headers,
                )
                return response
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            logger.warning(
                "payment_factory[%s]: tentative %d/%d échouée (%s)",
                provider_name,
                attempt + 1,
                NETWORK_RETRY_COUNT + 1,
                type(exc).__name__,
            )
            if attempt < NETWORK_RETRY_COUNT:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))

    # Tous les retries ont échoué
    logger.error(
        "payment_factory[%s]: appel %s %s en échec après %d tentatives",
        provider_name,
        method,
        url,
        NETWORK_RETRY_COUNT + 1,
    )
    raise HTTPException(
        status_code=502,
        detail=f"Erreur réseau provider {provider_name}",
    ) from last_exc


# ── Flouci ────────────────────────────────────────────────────────────────────
class FlouciProvider(_BaseProvider):
    """Flouci Pay — passerelle tunisienne. Doc : https://developers.flouci.com/."""

    name = "flouci"
    BASE_URL = "https://developers.flouci.app/api"

    async def create_payment_link(
        self,
        amount: float,
        currency: str = "TND",
        description: str | None = None,
        reference: str | None = None,
        customer_phone: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        app_token = self.cfg.get("app_token")
        app_secret = self.cfg.get("app_secret")
        if not app_token or not app_secret:
            raise HTTPException(
                status_code=400,
                detail="Flouci non configuré (app_token/app_secret manquants)",
            )

        # Flouci attend le montant en millimes (1 TND = 1000 millimes)
        amount_millimes = int(round(float(amount) * 1000))
        session_id = reference or "auto-session"

        success_link = kwargs.get("success_url") or f"{settings.SERVER_DOMAIN}/payment/success"
        fail_link = kwargs.get("fail_url") or f"{settings.SERVER_DOMAIN}/payment/fail"

        payload = {
            "app_token": app_token,
            "app_secret": app_secret,
            "amount": str(amount_millimes),
            "accept_card": "true",
            "session_timeout_secs": 1200,
            "success_link": success_link,
            "fail_link": fail_link,
            "developer_tracking_id": session_id,
        }

        response = await _http_request_with_retry(
            "POST",
            f"{self.BASE_URL}/generate_payment",
            json_payload=payload,
            provider_name=self.name,
        )

        if response.status_code >= 400:
            logger.error("payment_factory[flouci]: HTTP %d sur generate_payment", response.status_code)
            raise HTTPException(status_code=502, detail="Flouci a refusé la requête")

        data = response.json()
        result = data.get("result") or {}
        link = result.get("link") or data.get("link")
        payment_id = result.get("payment_id") or data.get("payment_id")
        if not link or not payment_id:
            logger.error("payment_factory[flouci]: réponse invalide (clés manquantes)")
            raise HTTPException(status_code=502, detail="Réponse Flouci invalide")

        return {"url": link, "id": payment_id, "provider": self.name}

    def verify_webhook_signature(self, payload: bytes, headers: dict[str, str], **kwargs: Any) -> tuple[bool, str]:
        # SEC-FIX (audit, CRITICAL): previously `if not header: return True, "unsigned"`
        # let anyone bypass verification by simply omitting the signature header.
        # Flouci supports signed webhooks, so a missing header must fail closed —
        # "unsigned"/"not_applicable" is only for providers with no signing concept
        # at all (e.g. Cash), never for a provider whose signature is just absent.
        header = headers.get("x-flouci-signature") or headers.get("x-signature") or ""
        secret = self.cfg.get("webhook_secret") or self.cfg.get("app_secret")
        if not header:
            return False, "missing_signature"
        if not secret:
            return False, "missing_secret"
        digest = hmac.new(str(secret).encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, header), "verified" if hmac.compare_digest(digest, header) else "invalid"

    async def verify_payment(self, payment_ref: str, **kwargs: Any) -> dict[str, Any]:
        app_token = self.cfg.get("app_token")
        app_secret = self.cfg.get("app_secret")
        if not app_token or not app_secret:
            raise HTTPException(
                status_code=400,
                detail="Flouci non configuré (app_token/app_secret manquants)",
            )

        response = await _http_request_with_retry(
            "GET",
            f"{self.BASE_URL}/verify_payment/{payment_ref}",
            headers={"apppublic": app_token, "appsecret": app_secret},
            provider_name=self.name,
        )

        if response.status_code >= 400:
            return {"status": "failed", "provider": self.name}

        data = response.json()
        result = data.get("result") or data
        raw_status = str(result.get("status") or "").upper()

        if raw_status in {"SUCCESS", "PAID", "COMPLETED"}:
            status = "paid"
        elif raw_status in {"FAILED", "DECLINED", "CANCELLED", "EXPIRED"}:
            status = "failed"
        else:
            status = "pending"

        return {"status": status, "provider": self.name, "raw": raw_status}


# ── Konnect ──────────────────────────────────────────────────────────────────
class KonnectProvider(_BaseProvider):
    """Konnect Network — passerelle tunisienne. Doc : https://api.konnect.network/."""

    name = "konnect"
    BASE_URL = "https://api.konnect.network/api/v2"

    async def create_payment_link(
        self,
        amount: float,
        currency: str = "TND",
        description: str | None = None,
        reference: str | None = None,
        customer_phone: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        api_key = self.cfg.get("api_key")
        receiver_wallet_id = self.cfg.get("receiver_wallet_id") or self.cfg.get("wallet_id")
        if not api_key or not receiver_wallet_id:
            raise HTTPException(
                status_code=400,
                detail="Konnect non configuré (api_key/receiver_wallet_id manquants)",
            )

        # Konnect attend également les montants en millimes pour TND
        amount_millimes = int(round(float(amount) * 1000))

        payload: dict[str, Any] = {
            "receiverWalletId": receiver_wallet_id,
            "token": currency.upper(),
            "amount": amount_millimes,
            "type": "immediate",
            "description": description or "Paiement AutoCommerce",
            "lifespan": 10,  # minutes
            "checkoutForm": False,
            "addPaymentFeesToAmount": False,
            "orderId": reference or "",
        }
        if customer_phone:
            payload["phoneNumber"] = customer_phone

        response = await _http_request_with_retry(
            "POST",
            f"{self.BASE_URL}/payments/init-payment",
            json_payload=payload,
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            provider_name=self.name,
        )

        if response.status_code >= 400:
            logger.error("payment_factory[konnect]: HTTP %d sur init-payment", response.status_code)
            raise HTTPException(status_code=502, detail="Konnect a refusé la requête")

        data = response.json()
        pay_url = data.get("payUrl") or data.get("payUrlComplete")
        payment_ref = data.get("paymentRef") or data.get("paymentId")
        if not pay_url or not payment_ref:
            logger.error("payment_factory[konnect]: réponse invalide")
            raise HTTPException(status_code=502, detail="Réponse Konnect invalide")

        return {"url": pay_url, "id": payment_ref, "provider": self.name}

    def verify_webhook_signature(self, payload: bytes, headers: dict[str, str], **kwargs: Any) -> tuple[bool, str]:
        # SEC-FIX (audit, CRITICAL): same fail-open bypass as Flouci — fixed identically.
        header = headers.get("x-signature") or headers.get("x-konnect-signature") or ""
        secret = self.cfg.get("webhook_secret") or self.cfg.get("api_key")
        if not header:
            return False, "missing_signature"
        if not secret:
            return False, "missing_secret"
        digest = hmac.new(str(secret).encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, header), "verified" if hmac.compare_digest(digest, header) else "invalid"

    async def verify_payment(self, payment_ref: str, **kwargs: Any) -> dict[str, Any]:
        api_key = self.cfg.get("api_key")
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="Konnect non configuré (api_key manquante)",
            )

        response = await _http_request_with_retry(
            "GET",
            f"{self.BASE_URL}/payments/{payment_ref}",
            headers={"x-api-key": api_key},
            provider_name=self.name,
        )

        if response.status_code >= 400:
            return {"status": "failed", "provider": self.name}

        data = response.json()
        payment = data.get("payment") or data
        raw_status = str(payment.get("status") or "").lower()

        if raw_status in {"completed", "paid", "success"}:
            status = "paid"
        elif raw_status in {"failed", "expired", "cancelled", "canceled"}:
            status = "failed"
        else:
            status = "pending"

        return {"status": status, "provider": self.name, "raw": raw_status}


# ── Stripe ───────────────────────────────────────────────────────────────────
class StripeProvider(_BaseProvider):
    """Stripe Checkout — international. Doc : https://stripe.com/docs/api/checkout/sessions."""

    name = "stripe"

    async def create_payment_link(
        self,
        amount: float,
        currency: str = "USD",
        description: str | None = None,
        reference: str | None = None,
        customer_phone: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        secret_key = self.cfg.get("secret_key") or self.cfg.get("api_key")
        if not secret_key:
            raise HTTPException(
                status_code=400,
                detail="Stripe non configuré (secret_key manquante)",
            )

        success_url = kwargs.get("success_url") or f"{settings.SERVER_DOMAIN}/payment/success"
        cancel_url = kwargs.get("cancel_url") or f"{settings.SERVER_DOMAIN}/payment/cancel"

        try:
            import stripe  # local import — package optionnel
        except ImportError as exc:
            logger.error("payment_factory[stripe]: package 'stripe' non installé")
            raise HTTPException(
                status_code=503,
                detail="Module Stripe indisponible sur ce serveur",
            ) from exc

        stripe.api_key = secret_key

        # Stripe attend le montant en plus petite unité (cents pour USD/EUR, etc.)
        amount_minor = int(round(float(amount) * 100))

        try:
            # Stripe SDK est synchrone — on délègue à un thread pour ne pas
            # bloquer la boucle asyncio.
            session = await asyncio.to_thread(
                stripe.checkout.Session.create,
                payment_method_types=["card"],
                line_items=[
                    {
                        "price_data": {
                            "currency": currency.lower(),
                            "product_data": {"name": description or "Paiement AutoCommerce"},
                            "unit_amount": amount_minor,
                        },
                        "quantity": 1,
                    }
                ],
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=reference,
            )
        except Exception as exc:  # noqa: BLE001 — Stripe lève des exceptions spécifiques mais on les abstrait
            # Ne logue PAS le secret_key. Stripe peut inclure des bouts d'auth header dans certains messages :
            # on logue uniquement le type d'erreur.
            logger.error("payment_factory[stripe]: échec création session (%s)", type(exc).__name__)
            raise HTTPException(status_code=502, detail="Stripe a refusé la requête") from exc

        return {
            "url": session.url,
            "id": session.id,
            "provider": self.name,
        }

    def verify_webhook_signature(self, payload: bytes, headers: dict[str, str], **kwargs: Any) -> tuple[bool, str]:
        signature = headers.get("stripe-signature") or ""
        secret = self.cfg.get("webhook_secret")
        if not signature:
            return False, "missing_signature"
        if not secret:
            return False, "missing_secret"
        try:
            import stripe
            stripe.Webhook.construct_event(payload, signature, secret)
            return True, "verified"
        except Exception:
            return False, "invalid"

    async def verify_payment(self, payment_ref: str, **kwargs: Any) -> dict[str, Any]:
        secret_key = self.cfg.get("secret_key") or self.cfg.get("api_key")
        if not secret_key:
            raise HTTPException(
                status_code=400,
                detail="Stripe non configuré (secret_key manquante)",
            )

        try:
            import stripe
        except ImportError as exc:
            raise HTTPException(
                status_code=503,
                detail="Module Stripe indisponible sur ce serveur",
            ) from exc

        stripe.api_key = secret_key

        try:
            session = await asyncio.to_thread(stripe.checkout.Session.retrieve, payment_ref)
        except Exception as exc:  # noqa: BLE001
            logger.error("payment_factory[stripe]: échec retrieve session (%s)", type(exc).__name__)
            raise HTTPException(status_code=502, detail="Stripe a refusé la requête") from exc

        raw_status = str(getattr(session, "payment_status", "") or "").lower()
        if raw_status == "paid":
            status = "paid"
        elif raw_status in {"unpaid", "no_payment_required"}:
            status = "pending"
        else:
            status = "failed"

        return {"status": status, "provider": self.name, "raw": raw_status}

    async def refund_payment(self, payment_ref: str, amount: float | None = None, **kwargs: Any) -> dict[str, Any]:
        secret_key = self.cfg.get("secret_key") or self.cfg.get("api_key")
        if not secret_key:
            raise HTTPException(status_code=400, detail="Stripe non configuré (secret_key manquante)")
        try:
            import stripe
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="Module Stripe indisponible sur ce serveur") from exc
        stripe.api_key = secret_key
        try:
            session = await asyncio.to_thread(stripe.checkout.Session.retrieve, payment_ref)
            payment_intent = getattr(session, "payment_intent", None) or (session.get("payment_intent") if isinstance(session, dict) else None)
            if not payment_intent:
                return {"status": "manual_required", "provider": self.name, "payment_ref": payment_ref}
            params = {"payment_intent": payment_intent}
            if amount is not None:
                params["amount"] = int(round(float(amount) * 100))
            refund = await asyncio.to_thread(stripe.Refund.create, **params)
            return {"status": "refunded", "provider": self.name, "refund_id": getattr(refund, "id", None)}
        except Exception as exc:
            logger.error("payment_factory[stripe]: refund failed (%s)", type(exc).__name__)
            raise HTTPException(status_code=502, detail="Stripe refund failed") from exc

    async def cancel_payment(self, payment_ref: str, **kwargs: Any) -> dict[str, Any]:
        secret_key = self.cfg.get("secret_key") or self.cfg.get("api_key")
        if not secret_key:
            raise HTTPException(status_code=400, detail="Stripe non configuré (secret_key manquante)")
        try:
            import stripe
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="Module Stripe indisponible sur ce serveur") from exc
        stripe.api_key = secret_key
        try:
            session = await asyncio.to_thread(stripe.checkout.Session.expire, payment_ref)
            return {"status": "cancelled", "provider": self.name, "session_id": getattr(session, "id", None) or payment_ref}
        except Exception as exc:
            logger.error("payment_factory[stripe]: cancel failed (%s)", type(exc).__name__)
            raise HTTPException(status_code=502, detail="Stripe cancel failed") from exc


# ── Cash ─────────────────────────────────────────────────────────────────────
class CashProvider(_BaseProvider):
    """Paiement à la livraison — ne nécessite aucun secret, jamais d'URL."""

    name = "cash"

    async def create_payment_link(
        self,
        amount: float,
        currency: str = "TND",
        description: str | None = None,
        reference: str | None = None,
        customer_phone: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "url": None,
            "id": reference,
            "provider": self.name,
            "method": "cash",
            "instruction": "Paiement à la livraison",
        }

    async def verify_payment(self, payment_ref: str, **kwargs: Any) -> dict[str, Any]:
        # Pas de vérification automatique — c'est le livreur qui confirme.
        return {"status": "pending_cash", "provider": self.name}




# ── Paymee ────────────────────────────────────────────────────────────────────
class PaymeeProvider(_BaseProvider):
    """Paymee — passerelle tunisienne. Doc : https://dev.paymee.tn/."""

    name = "paymee"
    BASE_URL = "https://app.paymee.tn/api/v2"

    def verify_webhook_signature(self, payload: bytes, headers: dict[str, str], **kwargs: Any) -> tuple[bool, str]:
        # SEC-FIX (audit, CRITICAL): PaymeeProvider had no override at all, so it
        # silently inherited `_BaseProvider`'s `(True, "not_applicable")` — every
        # Paymee webhook was accepted unconditionally, with no signature check.
        # Paymee's official scheme (dev.paymee.tn) is a body-level checksum, not a
        # header — same formula already used and verified in api/v1/payments.py:
        # SHA256(api_key + "%.3f" % amount + token).
        import hashlib
        import json as _json
        api_key = self.cfg.get("api_key")
        if not api_key:
            return False, "missing_secret"
        try:
            data = _json.loads(payload)
        except (ValueError, TypeError):
            return False, "invalid_payload"
        received = str(data.get("check_sum") or "").strip().lower()
        token = str(data.get("token") or "").strip()
        amount = data.get("amount")
        if not received or not token or amount is None:
            return False, "missing_signature"
        try:
            amount_f = float(amount)
        except (TypeError, ValueError):
            return False, "invalid_payload"
        expected = hashlib.sha256(f"{api_key}{amount_f:.3f}{token}".encode()).hexdigest()
        return hmac.compare_digest(received, expected), (
            "verified" if hmac.compare_digest(received, expected) else "invalid"
        )

    async def create_payment_link(
        self,
        amount: float,
        currency: str = "TND",
        description: str | None = None,
        reference: str | None = None,
        customer_phone: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        api_key = self.cfg.get("api_key")
        vendor_id = self.cfg.get("vendor_id")
        if not api_key or not vendor_id:
            raise HTTPException(
                status_code=400,
                detail="Paymee non configuré (api_key/vendor_id manquants)",
            )

        note = description or "Paiement AutoCommerce"
        success_url = kwargs.get("success_url") or f"{settings.SERVER_DOMAIN}/payment/success"
        cancel_url = kwargs.get("cancel_url") or f"{settings.SERVER_DOMAIN}/payment/cancel"

        payload: dict[str, Any] = {
            "vendor": int(vendor_id),
            "amount": round(float(amount), 3),
            "note": note[:100],
            "first_name": "Client",
            "last_name": "AutoCommerce",
            "email": kwargs.get("customer_email") or "client@autocommerce.tn",
            "phone": customer_phone or "",
            "return_url": success_url,
            "cancel_url": cancel_url,
            "webhook_url": f"{settings.SERVER_DOMAIN}/api/v1/payments/paymee-webhook",
            "order_id": reference or "",
            "currency": currency.upper(),
        }

        response = await _http_request_with_retry(
            "POST",
            f"{self.BASE_URL}/payments/create",
            json_payload=payload,
            headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"},
            provider_name=self.name,
        )

        if response.status_code >= 400:
            logger.error("payment_factory[paymee]: HTTP %d sur create", response.status_code)
            raise HTTPException(status_code=502, detail="Paymee a refusé la requête")

        data = response.json()
        if not data.get("status") or not data.get("data", {}).get("token"):
            logger.error("payment_factory[paymee]: réponse invalide %s", data)
            raise HTTPException(status_code=502, detail="Réponse Paymee invalide")

        token = data["data"]["token"]
        pay_url = f"https://app.paymee.tn/gateway/{token}"

        return {"url": pay_url, "id": token, "provider": self.name}

    async def verify_payment(self, payment_ref: str, **kwargs: Any) -> dict[str, Any]:
        api_key = self.cfg.get("api_key")
        if not api_key:
            raise HTTPException(status_code=400, detail="Paymee non configuré (api_key manquante)")

        response = await _http_request_with_retry(
            "GET",
            f"{self.BASE_URL}/payments/{payment_ref}/check",
            headers={"Authorization": f"Token {api_key}"},
            provider_name=self.name,
        )

        if response.status_code >= 400:
            return {"status": "failed", "provider": self.name}

        data = response.json()
        payment_data = data.get("data") or data
        # Paymee mock in tests uses 'status', production uses 'payment_status'
        raw_status = str(payment_data.get("payment_status") or payment_data.get("status") or "").lower()

        if raw_status in {"completed", "paid", "success"}:
            status = "paid"
        elif raw_status in {"failed", "expired", "cancelled"}:
            status = "failed"
        else:
            status = "pending"

        return {"status": status, "provider": self.name, "raw": raw_status}

# ══════════════════════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════════════════════

_PROVIDER_REGISTRY: dict[str, type[_BaseProvider]] = {
    "flouci": FlouciProvider,
    "konnect": KonnectProvider,
    "stripe": StripeProvider,
    "paymee": PaymeeProvider,
    "cash": CashProvider,
}


def verify_provider_webhook_signature(provider_name: str, payload: bytes, headers: dict[str, str], cfg: dict[str, Any] | None = None) -> tuple[bool, str]:
    provider = PaymentFactory.get(provider_name, cfg or {})
    normalized_headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    return provider.verify_webhook_signature(payload, normalized_headers)



class PaymentFactory:
    """Factory tenant-aware des providers de paiement."""

    @staticmethod
    def get(provider_name: str, cfg: dict[str, Any] | None = None) -> _BaseProvider:
        """Instancie un provider par son nom.

        `cfg` est attendu DÉJÀ déchiffré (l'appelant de api/v1/payment_links.py
        utilise `_decrypt_cfg` avant de passer ici). Pour `cash`, `cfg` peut être None.
        """
        cls = _PROVIDER_REGISTRY.get(provider_name.lower())
        if cls is None:
            raise HTTPException(
                status_code=400,
                detail=f"Provider de paiement inconnu : {provider_name}",
            )
        return cls(cfg or {})

    @staticmethod
    async def get_provider(store_id: int, db: AsyncSession) -> _BaseProvider:
        """Charge le Store, résout le provider par défaut et retourne l'adapter prêt à l'emploi.

        Étapes :
          1. SELECT du Store.
          2. Résolution du provider via `_resolve_provider_name(country, payment_config)`.
          3. Déchiffrement de la config provider (`_decrypt_config`).
          4. Instanciation via `get(provider_name, cfg)`.

        Lève HTTPException(404) si le Store n'existe pas.
        """
        result = await db.execute(select(Store).where(Store.id == store_id))
        store = result.scalar_one_or_none()
        if store is None:
            raise HTTPException(status_code=404, detail=f"Store {store_id} introuvable")

        provider_name = _resolve_provider_name(store.country, store.payment_config)

        if provider_name == "cash":
            return CashProvider({})

        raw_cfg = (store.payment_config or {}).get(provider_name) or {}
        decrypted = _decrypt_config(raw_cfg)
        return PaymentFactory.get(provider_name, decrypted)
