"""api/v1/payments.py — Payment webhooks + order payment initiation with fail-closed security.

Phase 3 — Paymee checksum officiel :
  - Vérification cryptographique SHA256 du check_sum Paymee (doc officielle dev.paymee.tn).
  - Rejet des callbacks invalides avec journalisation FRAUD_ATTEMPT.
  - Comparaison timing-safe via hmac.compare_digest.
  - Aucune régression sur Flouci, Clix, TnPay.
"""

import hashlib
import hmac
import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from middleware.tenant import current_tenant_id
from models.database import Order, OrderStatus, Store, get_db
from services.payment_factory import PaymentFactory
from services.redis_lock import lock_service
from services.tasks import reconcile_payment
from services.workflow_events import record_workflow_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["Payments"])

SUPPORTED_PROVIDERS = ("flouci", "clix", "tnpay", "cash", "paymee")


class PaymentIntentRequest(BaseModel):
    order_id: int
    provider: Literal["flouci", "clix", "tnpay", "cash", "paymee"]


def _decrypt_cfg(raw_cfg: dict) -> dict:
    decrypted = {}
    for k, v in raw_cfg.items():
        if isinstance(v, str) and v.startswith("enc_"):
            try:
                decrypted[k] = settings.decrypt(v[4:])
            except Exception as _exc:
                logger.error("Failed to decrypt payment config field '%s'", k)
                raise HTTPException(status_code=500, detail="Payment config decryption failed")
        else:
            decrypted[k] = v
    return decrypted


async def _load_store_payment_cfg(db: AsyncSession, store_id: int, provider: str) -> dict:
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store or not store.payment_config:
        raise HTTPException(status_code=400, detail="No payment configuration for this store")
    raw_cfg = store.payment_config.get(provider)
    if not raw_cfg:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider}' not configured. Available: {list(store.payment_config.keys())}",
        )
    return _decrypt_cfg(raw_cfg)


async def _record_payment_event(
    db: AsyncSession,
    *,
    provider: str,
    status: str,
    event_id: str | None,
    order_id: str | None,
    payload: dict[str, object],
    signature_status: str | None,
    tenant_id: int | None = None,
    error_message: str | None = None,
) -> None:
    await record_workflow_event(
        db,
        workflow_type="payment_webhook",
        status=status,
        provider=provider,
        tenant_id=tenant_id,
        external_event_id=event_id,
        message_id=order_id,
        signature_status=signature_status,
        payload_json=payload,
        error_message=error_message,
        retryable=status in {"failed"},
        dlq_name="payments.dlq" if status == "failed" else None,
    )


def _extract_bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return auth.strip()


async def _load_order_and_cfg(db: AsyncSession, provider: str, order_id: str) -> tuple[Order, dict]:
    try:
        order_id_int = int(order_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid order_id")
    order_result = await db.execute(
        select(Order).where(
            Order.id == order_id_int,
            Order.payment_provider == provider,
        )
    )
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    cfg = await _load_store_payment_cfg(db, order.store_id, provider)
    return order, cfg


async def _reject_payment_webhook(
    db: AsyncSession,
    *,
    provider: str,
    event_id: str | None,
    order_id: str | None,
    payload: dict[str, object],
    tenant_id: int | None,
    reason: str,
) -> None:
    await _record_payment_event(
        db,
        provider=provider,
        status="rejected",
        event_id=event_id,
        order_id=order_id,
        payload=payload,
        signature_status="rejected",
        tenant_id=tenant_id,
        error_message=reason,
    )
    await db.commit()
    raise HTTPException(status_code=401, detail=reason)


def _compute_hmac(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _validate_flouci(db, body, request, payload, event_id, order_id):
    order, cfg = await _load_order_and_cfg(db, "flouci", order_id)
    secret = cfg.get("secret_key", "")
    signature = request.headers.get("X-Flouci-Signature", "")
    if not secret or not signature:
        await _reject_payment_webhook(db, provider="flouci", event_id=event_id, order_id=order_id, payload=payload, tenant_id=order.store_id, reason="Missing Flouci signature or secret")
    if not hmac.compare_digest(signature, _compute_hmac(secret, body)):
        await _reject_payment_webhook(db, provider="flouci", event_id=event_id, order_id=order_id, payload=payload, tenant_id=order.store_id, reason="Invalid Flouci signature")
    return int(order.store_id)


async def _validate_clix(db, request, payload, event_id, order_id):
    order, cfg = await _load_order_and_cfg(db, "clix", order_id)
    expected = str(cfg.get("webhook_token") or cfg.get("secret_key") or "").strip()
    received = (
        request.headers.get("X-Clix-Signature", "")
        or request.headers.get("X-Clix-Token", "")
        or _extract_bearer_token(request)
        or str(payload.get("webhook_token") or "")
    ).strip()
    if not expected or not received:
        await _reject_payment_webhook(db, provider="clix", event_id=event_id, order_id=order_id, payload=payload, tenant_id=order.store_id, reason="Missing Clix webhook token")
    if not hmac.compare_digest(received, expected):
        await _reject_payment_webhook(db, provider="clix", event_id=event_id, order_id=order_id, payload=payload, tenant_id=order.store_id, reason="Invalid Clix webhook token")
    return int(order.store_id)


async def _validate_tnpay(db, request, payload, event_id, order_id):
    order, cfg = await _load_order_and_cfg(db, "tnpay", order_id)
    expected = str(cfg.get("webhook_token") or "").strip()
    received = (request.headers.get("X-TnPay-Token", "") or str(payload.get("webhook_token") or "")).strip()
    if not expected or not received:
        await _reject_payment_webhook(db, provider="tnpay", event_id=event_id, order_id=order_id, payload=payload, tenant_id=order.store_id, reason="Missing TnPay webhook token")
    if not hmac.compare_digest(received, expected):
        await _reject_payment_webhook(db, provider="tnpay", event_id=event_id, order_id=order_id, payload=payload, tenant_id=order.store_id, reason="Invalid TnPay webhook token")
    return int(order.store_id)


# ── Phase 3 : Checksum Paymee officiel ────────────────────────────────────────

def compute_paymee_checksum(api_key: str, amount: float, token: str) -> str:
    """Calcule le check_sum Paymee officiel (https://dev.paymee.tn/).

    Formule : SHA256( api_key + "%.3f" % amount + token )
    Encodage UTF-8, digest hexadécimal minuscule.

    Utilisé des deux côtés :
      - Dans les tests pour générer un checksum valide.
      - Dans _validate_paymee() pour vérifier le callback entrant.
    """
    data = f"{api_key}{amount:.3f}{token}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


async def _validate_paymee(
    db: AsyncSession,
    payload: dict[str, object],
    event_id: str,
    order_id: str,
) -> int:
    """Vérifie le check_sum Paymee et rejette les callbacks frauduleux.

    Sécurité :
      1. Vérification SHA256 timing-safe via hmac.compare_digest.
      2. Montant pris depuis la commande DB (pas depuis le payload) pour
         éviter qu'un attaquant injecte un montant différent.
      3. Journalisation PAYMEE_FRAUD_ATTEMPT sur tout échec.
      4. check_sum toujours REDACTED dans les logs (ne jamais logger le hash reçu).
    """
    order, cfg = await _load_order_and_cfg(db, "paymee", order_id)
    api_key = cfg.get("api_key", "")

    received_checksum = str(payload.get("check_sum") or "").strip().lower()
    token = str(payload.get("token") or "").strip()

    if not api_key:
        logger.error(
            "PAYMEE_CONFIG_ERROR store_id=%s order_id=%s api_key manquante",
            order.store_id, order_id,
        )
        await _reject_payment_webhook(
            db, provider="paymee", event_id=event_id, order_id=order_id,
            payload=payload, tenant_id=order.store_id,
            reason="Paymee api_key not configured",
        )

    if not received_checksum or not token:
        logger.warning(
            "PAYMEE_FRAUD_ATTEMPT store_id=%s order_id=%s "
            "check_sum_present=%s token_present=%s",
            order.store_id, order_id, bool(received_checksum), bool(token),
        )
        await _reject_payment_webhook(
            db, provider="paymee", event_id=event_id, order_id=order_id,
            payload={**payload, "check_sum": "REDACTED"},
            tenant_id=order.store_id,
            reason="Missing Paymee check_sum or token",
        )

    # Montant depuis la commande DB pour éviter l'injection de montant
    try:
        amount = float(order.total_amount)
    except (TypeError, ValueError):
        amount = float(payload.get("amount") or 0)

    expected_checksum = compute_paymee_checksum(api_key, amount, token)

    if not hmac.compare_digest(received_checksum, expected_checksum):
        logger.warning(
            "PAYMEE_FRAUD_ATTEMPT store_id=%s order_id=%s checksum_mismatch=True",
            order.store_id, order_id,
        )
        await _reject_payment_webhook(
            db, provider="paymee", event_id=event_id, order_id=order_id,
            payload={**payload, "check_sum": "REDACTED"},
            tenant_id=order.store_id,
            reason="Invalid Paymee check_sum — possible fraud attempt",
        )

    logger.info(
        "PAYMEE_CHECKSUM_OK store_id=%s order_id=%s",
        order.store_id, order_id,
    )
    return int(order.store_id)


from api.v1._deps import get_store_id as _sid


@router.post("/intent")
async def create_payment_intent(body: PaymentIntentRequest, db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    if not store_id:
        raise HTTPException(status_code=401, detail="No tenant context")

    result = await db.execute(select(Order).where(Order.id == body.order_id, Order.store_id == store_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != OrderStatus.CONFIRMED:
        raise HTTPException(status_code=400, detail=f"Order must be 'confirmed', got '{order.status}'")

    provider_cfg = await _load_store_payment_cfg(db, store_id, body.provider)
    adapter = PaymentFactory.get(body.provider, provider_cfg)
    intent = await adapter.create_intent(order.total_amount, str(order.id))

    order.payment_provider = body.provider
    await db.commit()
    return {"order_id": order.id, "amount": order.total_amount, **intent}


@router.post("/webhook/flouci")
async def flouci_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.body()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    event_id = data.get("id") or data.get("event_id", "")
    order_id = str(data.get("order_id", ""))
    transaction_id = data.get("transaction_id", "")
    status = data.get("status", "")
    if not event_id or not order_id:
        raise HTTPException(status_code=400, detail="Missing event_id or order_id")
    tenant_id = await _validate_flouci(db, body, request, data, event_id, order_id)
    await _record_payment_event(db, provider="flouci", status="validated", event_id=event_id, order_id=order_id, payload=data, signature_status="validated", tenant_id=tenant_id)
    if not await lock_service.acquire(f"payment:flouci:{event_id}", ttl=172800):
        await _record_payment_event(db, provider="flouci", status="replayed", event_id=event_id, order_id=order_id, payload=data, signature_status="validated", tenant_id=tenant_id)
        await db.commit()
        return {"status": "duplicate_ignored"}
    reconcile_payment.delay("flouci", transaction_id, event_id, order_id, status)
    await _record_payment_event(db, provider="flouci", status="queued", event_id=event_id, order_id=order_id, payload=data, signature_status="validated", tenant_id=tenant_id)
    await db.commit()
    return {"status": "queued"}


@router.post("/webhook/clix")
async def clix_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.body()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    event_id = data.get("transaction_id", "")
    order_id = str(data.get("reference", ""))
    status = data.get("status", "")
    if not event_id or not order_id:
        raise HTTPException(status_code=400, detail="Missing transaction_id or reference")
    tenant_id = await _validate_clix(db, request, data, event_id, order_id)
    await _record_payment_event(db, provider="clix", status="validated", event_id=event_id, order_id=order_id, payload=data, signature_status="validated", tenant_id=tenant_id)
    if not await lock_service.acquire(f"payment:clix:{event_id}", ttl=172800):
        await _record_payment_event(db, provider="clix", status="replayed", event_id=event_id, order_id=order_id, payload=data, signature_status="validated", tenant_id=tenant_id)
        await db.commit()
        return {"status": "duplicate_ignored"}
    reconcile_payment.delay("clix", event_id, event_id, order_id, status)
    await _record_payment_event(db, provider="clix", status="queued", event_id=event_id, order_id=order_id, payload=data, signature_status="validated", tenant_id=tenant_id)
    await db.commit()
    return {"status": "queued"}


@router.post("/webhook/tnpay")
async def tnpay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.body()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    event_id = data.get("transaction_id", "")
    order_id = str(data.get("order_id", ""))
    status = data.get("status", "")
    if not event_id or not order_id:
        raise HTTPException(status_code=400, detail="Missing transaction_id or order_id")
    tenant_id = await _validate_tnpay(db, request, data, event_id, order_id)
    await _record_payment_event(db, provider="tnpay", status="validated", event_id=event_id, order_id=order_id, payload=data, signature_status="validated", tenant_id=tenant_id)
    if not await lock_service.acquire(f"payment:tnpay:{event_id}", ttl=172800):
        await _record_payment_event(db, provider="tnpay", status="replayed", event_id=event_id, order_id=order_id, payload=data, signature_status="validated", tenant_id=tenant_id)
        await db.commit()
        return {"status": "duplicate_ignored"}
    reconcile_payment.delay("tnpay", event_id, event_id, order_id, status)
    await _record_payment_event(db, provider="tnpay", status="queued", event_id=event_id, order_id=order_id, payload=data, signature_status="validated", tenant_id=tenant_id)
    await db.commit()
    return {"status": "queued"}


@router.post("/webhook/paymee")
async def paymee_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Webhook Paymee avec vérification cryptographique officielle du check_sum.

    Paymee envoie :
      { "token": "...", "amount": 100.500, "check_sum": "sha256hex...",
        "payment_status": "completed", "order_id": "42", ... }

    Sécurité :
      1. SHA256(api_key + "100.500" + token) == check_sum (timing-safe).
      2. Rejet 401 + journalisation FRAUD_ATTEMPT si checksum invalide.
      3. Lock Redis idempotent (évite le double-traitement).
      4. Dispatch Celery asynchrone — webhook 200 OK immédiat.
    """
    body = await request.body()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    token = str(data.get("token") or "")
    order_id = str(data.get("order_id") or "")
    payment_status = str(data.get("payment_status") or data.get("status") or "")

    if not token or not order_id:
        logger.warning("PAYMEE_WEBHOOK_INVALID missing token or order_id")
        raise HTTPException(status_code=400, detail="Missing token or order_id")

    tenant_id = await _validate_paymee(db, data, event_id=token, order_id=order_id)

    await _record_payment_event(
        db, provider="paymee", status="validated", event_id=token,
        order_id=order_id, payload={**data, "check_sum": "REDACTED"},
        signature_status="validated", tenant_id=tenant_id,
    )

    lock_key = f"payment:paymee:{token}"
    if not await lock_service.acquire(lock_key, ttl=172800):
        await _record_payment_event(
            db, provider="paymee", status="replayed", event_id=token,
            order_id=order_id, payload={**data, "check_sum": "REDACTED"},
            signature_status="validated", tenant_id=tenant_id,
        )
        await db.commit()
        return {"status": "duplicate_ignored"}

    reconcile_payment.delay("paymee", token, token, order_id, payment_status)

    await _record_payment_event(
        db, provider="paymee", status="queued", event_id=token,
        order_id=order_id, payload={**data, "check_sum": "REDACTED"},
        signature_status="validated", tenant_id=tenant_id,
    )
    await db.commit()
    return {"status": "queued"}
