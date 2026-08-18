"""api/v1/payment_links.py — liens de paiement + TVA + facturation (Plan A)."""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import get_store_id as _sid
from config import settings
from models.database import AsyncSessionLocal, Order, PaymentLink, Store, get_db
from services.email_service import send_invoice_email
from services.invoice_service import (
    create_and_save_invoice,
    create_credit_note_for_payment_link,
    export_accounting_csv,
    generate_invoice_number,
)
from services.payment_factory import PaymentFactory, verify_provider_webhook_signature
from services.payment_router import detect_country_from_phone, get_default_currency, resolve_provider_with_fallback
from services.promotions_service import apply_promotions_to_items, record_promotion_usage
from services.redis_lock import lock_service
from services.tax_service import calculate_manual_amount_taxes, calculate_order_taxes
from services.workflow_events import record_workflow_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payment-links", tags=["Payment Links"])

SUPPORTED_PROVIDERS = ("stripe", "flouci", "konnect", "paymee", "cash")


class CreatePaymentLinkRequest(BaseModel):
    amount: float | None = Field(None, gt=0)
    currency: str | None = Field(None, max_length=3)
    description: str | None = Field(None, min_length=1, max_length=500)
    provider: str | None = None
    customer_name: str | None = Field(None, max_length=255)
    customer_email: str | None = Field(None, max_length=255)
    customer_phone: str | None = Field(None, max_length=30)
    order_id: int | None = None
    channel: str | None = Field(default="manual")
    amount_is_tax_inclusive: bool | None = None
    country_code: str | None = Field(None, min_length=2, max_length=2)
    tax_category: str | None = Field(None, max_length=100)
    is_tax_exempt: bool = False
    coupon_codes: list[str] | None = None

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower()
        if normalized not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Provider non supporté : {value}")
        return normalized

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @model_validator(mode="after")
    def validate_amount_or_order(self):
        if self.order_id is None and self.amount is None:
            raise ValueError("amount requis si order_id absent")
        return self


class SendPaymentLinkRequest(BaseModel):
    channel: Literal["whatsapp", "facebook", "instagram", "sms", "email"]
    recipient: str
    message: str | None = None


class RefundPaymentLinkRequest(BaseModel):
    amount: float | None = Field(None, gt=0)
    reason: str | None = Field(None, max_length=255)


class PaymentLinkResponse(BaseModel):
    id: int
    provider: str
    url: str | None
    amount: float
    subtotal_amount: float | None = None
    tax_amount: float | None = None
    discount_amount: float | None = None
    promotion_codes: list[str] | None = None
    promotion_breakdown: list[dict[str, Any]] | None = None
    currency: str
    country_code: str | None = None
    description: str | None
    status: str
    invoice_url: str | None
    invoice_number: str | None
    channel: str | None
    customer_name: str | None
    customer_phone: str | None
    customer_email: str | None
    tax_breakdown: list[dict[str, Any]] | None = None
    refunded_amount: float | None = None
    failure_reason: str | None = None
    last_verified_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


def _get_store_id() -> int:
    store_id = _sid()
    if not store_id:
        raise HTTPException(status_code=401, detail="Contexte tenant manquant")
    return int(store_id)


def _decrypt_cfg(raw_cfg: dict[str, Any]) -> dict[str, Any]:
    decrypted: dict[str, Any] = {}
    for key, value in (raw_cfg or {}).items():
        if isinstance(value, str) and value.startswith("enc_"):
            decrypted[key] = settings.decrypt(value[4:])
        else:
            decrypted[key] = value
    return decrypted


async def _load_store(db: AsyncSession, store_id: int) -> Store:
    store = await db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Store non trouvé")
    return store


async def _resolve_provider_and_cfg(db: AsyncSession, store: Store, provider: str | None) -> tuple[str, dict[str, Any]]:
    payment_config = store.payment_config or {}
    if provider:
        if provider == "cash":
            return provider, {}
        if provider not in payment_config:
            raise HTTPException(status_code=400, detail=f"Provider '{provider}' non configuré pour ce store")
        return provider, _decrypt_cfg(payment_config.get(provider) or {})

    if not payment_config:
        return "cash", {}

    resolved = resolve_provider_with_fallback(store.country, payment_config)
    raw_cfg = payment_config.get(resolved) or {}
    return resolved, _decrypt_cfg(raw_cfg)


async def _load_order_for_store(db: AsyncSession, *, store_id: int, order_id: int) -> Order:
    order = (await db.execute(select(Order).where(Order.id == order_id, Order.store_id == store_id))).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    return order


@router.post("/", response_model=PaymentLinkResponse, status_code=201)
async def create_payment_link(
    body: CreatePaymentLinkRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    store_id = _get_store_id()
    store = await _load_store(db, store_id)
    provider, cfg = await _resolve_provider_and_cfg(db, store, body.provider)

    country_hint = body.country_code or detect_country_from_phone(body.customer_phone) or store.default_tax_country or store.country
    currency = body.currency or get_default_currency(country_hint)

    if body.order_id is not None:
        order = await _load_order_for_store(db, store_id=store_id, order_id=body.order_id)
        promotion_result = await apply_promotions_to_items(
            db,
            store=store,
            items=list(order.items or []),
            coupon_codes=body.coupon_codes or order.promotion_codes,
            country_code=country_hint,
            channel=body.channel,
            customer_id=order.customer_id,
            customer_email=body.customer_email,
            customer_phone=body.customer_phone,
            customer_name=body.customer_name,
        )
        order.items = promotion_result.items
        order.discount_amount = promotion_result.discount_amount
        order.promotion_codes = promotion_result.applied_coupon_codes
        order.promotion_breakdown = promotion_result.applied_promotions
        tax_result = await calculate_order_taxes(
            db,
            store=store,
            order=order,
            country_code=country_hint,
            customer_email=body.customer_email,
            customer_phone=body.customer_phone,
            prices_include_tax=body.amount_is_tax_inclusive,
        )
        order.subtotal_amount = tax_result.subtotal_amount
        order.tax_amount = tax_result.tax_amount
        order.country_code = tax_result.country_code
        order.tax_breakdown = tax_result.breakdown
        order.currency = currency
        order.total_amount = tax_result.total_amount
        total_amount = tax_result.total_amount
        description = body.description or f"Commande #{order.id}"
        subtotal_amount = tax_result.subtotal_amount
        tax_amount = tax_result.tax_amount
        tax_breakdown = tax_result.breakdown
        country_code = tax_result.country_code
        discount_amount = promotion_result.discount_amount
        promotion_codes = promotion_result.applied_coupon_codes
        promotion_breakdown = promotion_result.applied_promotions
    else:
        assert body.amount is not None
        description = body.description or "Paiement en ligne"
        promotion_result = await apply_promotions_to_items(
            db,
            store=store,
            items=[{
                "name": description,
                "qty": 1,
                "unit_price": Decimal(str(body.amount)),
                "tax_category": body.tax_category,
                "is_tax_exempt": body.is_tax_exempt,
            }],
            coupon_codes=body.coupon_codes,
            country_code=country_hint,
            channel=body.channel,
            customer_email=body.customer_email,
            customer_phone=body.customer_phone,
            customer_name=body.customer_name,
        )
        discounted_item = promotion_result.items[0]
        tax_result = await calculate_manual_amount_taxes(
            db,
            store=store,
            description=description,
            amount=Decimal(str(discounted_item.get("unit_price", body.amount))),
            country_code=country_hint,
            category=body.tax_category,
            customer_email=body.customer_email,
            customer_phone=body.customer_phone,
            prices_include_tax=body.amount_is_tax_inclusive,
            is_tax_exempt=body.is_tax_exempt,
        )
        total_amount = tax_result.total_amount
        subtotal_amount = tax_result.subtotal_amount
        tax_amount = tax_result.tax_amount
        tax_breakdown = tax_result.breakdown
        country_code = tax_result.country_code
        discount_amount = promotion_result.discount_amount
        promotion_codes = promotion_result.applied_coupon_codes
        promotion_breakdown = promotion_result.applied_promotions
        order = None

    import uuid
    reference = f"pl-{store_id}-{uuid.uuid4().hex[:12]}"
    adapter = PaymentFactory.get(provider, cfg)
    try:
        provider_result = await adapter.create_payment_link(
            amount=float(total_amount),
            currency=currency,
            description=description,
            reference=reference,
            customer_phone=body.customer_phone,
            customer_email=body.customer_email,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("payment_link create provider=%s failed: %s", provider, exc)
        raise HTTPException(status_code=502, detail=f"Erreur lors de la création du lien via {provider}") from exc

    payment_link = PaymentLink(
        store_id=store_id,
        order_id=body.order_id,
        provider=provider,
        url=provider_result.get("url"),
        amount=total_amount,
        subtotal_amount=subtotal_amount,
        tax_amount=tax_amount,
        discount_amount=discount_amount,
        promotion_codes=promotion_codes,
        promotion_breakdown=promotion_breakdown,
        currency=currency,
        country_code=country_code,
        tax_breakdown=tax_breakdown,
        description=description,
        status="pending",
        external_reference=provider_result.get("id") or reference,
        channel=body.channel or "manual",
        customer_name=body.customer_name,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        invoice_number=generate_invoice_number(store.id, prefix=store.invoice_prefix or "INV"),
    )
    payment_link.invoice_url = None
    db.add(payment_link)
    await db.flush()
    await record_promotion_usage(
        db,
        store_id=store_id,
        applied_promotions=promotion_breakdown or [],
        customer_id=getattr(order, "customer_id", None) if order is not None else None,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        payment_link_id=payment_link.id,
        order_id=body.order_id,
    )
    await db.commit()
    await db.refresh(payment_link)

    background_tasks.add_task(_generate_invoice_background, payment_link.id, store_id)
    return _to_response(payment_link)


@router.get("/", response_model=dict)
async def list_payment_links(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = None,
    provider: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    store_id = _get_store_id()
    offset = (page - 1) * limit
    stmt = select(PaymentLink).where(PaymentLink.store_id == store_id)
    count_stmt = select(func.count()).select_from(PaymentLink).where(PaymentLink.store_id == store_id)
    if status:
        stmt = stmt.where(PaymentLink.status == status)
        count_stmt = count_stmt.where(PaymentLink.status == status)
    if provider:
        stmt = stmt.where(PaymentLink.provider == provider)
        count_stmt = count_stmt.where(PaymentLink.provider == provider)
    stmt = stmt.order_by(PaymentLink.created_at.desc()).offset(offset).limit(limit)

    links = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()
    return {
        "items": [_to_response(link).model_dump() for link in links],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/analytics")
async def payment_links_analytics(db: AsyncSession = Depends(get_db)):
    store_id = _get_store_id()
    status_rows = await db.execute(
        select(PaymentLink.status, func.count().label("count"), func.sum(PaymentLink.amount).label("total"))
        .where(PaymentLink.store_id == store_id)
        .group_by(PaymentLink.status)
    )
    provider_rows = await db.execute(
        select(PaymentLink.provider, func.count().label("count"))
        .where(PaymentLink.store_id == store_id)
        .group_by(PaymentLink.provider)
    )
    by_status = {row.status: {"count": row.count, "total": float(row.total or 0)} for row in status_rows}
    by_provider = {row.provider: row.count for row in provider_rows}
    return {
        "by_status": by_status,
        "by_provider": by_provider,
        "revenue_paid": by_status.get("paid", {}).get("total", 0),
        "revenue_refunded": by_status.get("refunded", {}).get("total", 0),
        "pending_count": by_status.get("pending", {}).get("count", 0),
    }


@router.get("/accounting/export")
async def accounting_export(db: AsyncSession = Depends(get_db)):
    store_id = _get_store_id()
    csv_data = await export_accounting_csv(db, store_id=store_id)
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="accounting_export_{store_id}.csv"'},
    )


@router.get("/{link_id}", response_model=PaymentLinkResponse)
async def get_payment_link(link_id: int, db: AsyncSession = Depends(get_db)):
    link = await _get_link_or_404(db, link_id, _get_store_id())
    return _to_response(link)


@router.delete("/{link_id}", status_code=204)
async def delete_payment_link(link_id: int, db: AsyncSession = Depends(get_db)):
    link = await _get_link_or_404(db, link_id, _get_store_id())
    if link.status not in {"pending", "failed", "cancelled", "expired"}:
        raise HTTPException(status_code=400, detail="Suppression impossible pour ce statut")
    await db.delete(link)
    await db.commit()


@router.get("/{link_id}/invoice")
async def download_invoice(link_id: int, db: AsyncSession = Depends(get_db)):
    store_id = _get_store_id()
    link = await _get_link_or_404(db, link_id, store_id)
    if not link.invoice_number:
        raise HTTPException(status_code=404, detail="Facture non générée")
    pdf_path = link.invoice_pdf_path
    if not pdf_path or not os.path.exists(pdf_path):
        store = await _load_store(db, store_id)
        result = await create_and_save_invoice(db=db, payment_link=link, store=store)
        link.invoice_pdf_path = result.get("pdf_path")
        link.invoice_url = f"/api/v1/payment-links/{link.id}/invoice"
        await db.commit()
        pdf_path = link.invoice_pdf_path
    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Fichier PDF introuvable")
    return FileResponse(path=pdf_path, media_type="application/pdf", filename=f"facture_{link.invoice_number}.pdf")


@router.post("/{link_id}/send")
async def send_payment_link(
    link_id: int,
    body: SendPaymentLinkRequest,
    db: AsyncSession = Depends(get_db),
):
    store_id = _get_store_id()
    link = await _get_link_or_404(db, link_id, store_id)
    store = await _load_store(db, store_id)

    if body.channel == "email":
        if not body.recipient:
            raise HTTPException(status_code=400, detail="Email destinataire requis")
        invoice_url = f"{settings.SERVER_DOMAIN}/api/v1/payment-links/{link.id}/invoice"
        await send_invoice_email(body.recipient, invoice_url, link.invoice_number or str(link.id), store.name)
        send_result = {"status": "sent", "channel": "email"}
    elif body.channel == "whatsapp":
        send_result = await _send_via_whatsapp(store, body.recipient, _build_message(link, body.message))
    elif body.channel in {"facebook", "instagram", "sms"}:
        send_result = {"warning": f"Canal {body.channel} à compléter côté intégration"}
    else:
        raise HTTPException(status_code=400, detail="Canal non supporté")

    link.sent_at = datetime.now(UTC)
    link.channel = body.channel
    await db.commit()
    return {"success": True, **send_result}


@router.post("/{link_id}/verify")
async def verify_payment_link(link_id: int, db: AsyncSession = Depends(get_db)):
    store_id = _get_store_id()
    link = await _get_link_or_404(db, link_id, store_id)
    store = await _load_store(db, store_id)
    provider, cfg = await _resolve_provider_and_cfg(db, store, link.provider)
    adapter = PaymentFactory.get(provider, cfg)
    result = await adapter.verify_payment(link.external_reference or str(link.id))
    _apply_payment_status(link, result.get("status"), provider_payload=result)
    await db.commit()
    return {"payment_link_id": link.id, "provider": link.provider, **result}


@router.post("/{link_id}/refund")
async def refund_payment_link(
    link_id: int,
    body: RefundPaymentLinkRequest,
    db: AsyncSession = Depends(get_db),
):
    store_id = _get_store_id()
    link = await _get_link_or_404(db, link_id, store_id)
    if link.status not in {"paid", "refunded"}:
        raise HTTPException(status_code=400, detail="Seuls les liens payés peuvent être remboursés")
    store = await _load_store(db, store_id)
    provider, cfg = await _resolve_provider_and_cfg(db, store, link.provider)
    adapter = PaymentFactory.get(provider, cfg)
    refund_result = await adapter.refund_payment(link.external_reference or str(link.id), amount=body.amount)
    refunded_amount = Decimal(str(body.amount or link.amount or 0))
    previous_refunded = Decimal(str(link.refunded_amount or 0))
    link.refunded_amount = previous_refunded + refunded_amount
    link.status = "refunded" if Decimal(str(link.refunded_amount or 0)) >= Decimal(str(link.amount or 0)) else "paid"
    link.last_verified_at = datetime.now(UTC)
    link.provider_payload = {**(link.provider_payload or {}), "refund": refund_result}
    credit_note = await create_credit_note_for_payment_link(
        db,
        payment_link=link,
        store=store,
        refund_amount=body.amount,
        reason=body.reason,
    )
    await db.commit()
    return {"payment_link_id": link.id, "refund": refund_result, "credit_note": credit_note}


@router.post("/{link_id}/cancel")
async def cancel_payment_link(link_id: int, db: AsyncSession = Depends(get_db)):
    store_id = _get_store_id()
    link = await _get_link_or_404(db, link_id, store_id)
    if link.status == "paid":
        raise HTTPException(status_code=400, detail="Impossible d'annuler un lien déjà payé")
    store = await _load_store(db, store_id)
    provider, cfg = await _resolve_provider_and_cfg(db, store, link.provider)
    adapter = PaymentFactory.get(provider, cfg)
    cancel_result = await adapter.cancel_payment(link.external_reference or str(link.id))
    link.status = "cancelled"
    link.cancelled_at = datetime.now(UTC)
    link.last_verified_at = datetime.now(UTC)
    link.provider_payload = {**(link.provider_payload or {}), "cancel": cancel_result}
    await db.commit()
    return {"payment_link_id": link.id, "cancel": cancel_result}


@router.post("/webhook/{provider}")
async def payment_link_webhook(provider: str, request: Request, db: AsyncSession = Depends(get_db)):
    provider = provider.lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail="Provider non reconnu")

    payload = await request.body()
    data = _parse_payload(payload)
    external_reference = _extract_external_reference(data)
    event_id = _extract_event_id(data, provider, external_reference)
    if not external_reference:
        logger.warning("webhook payment provider=%s sans external_reference", provider)
        return {"status": "ignored", "reason": "no_reference"}

    link = (
        await db.execute(
            select(PaymentLink).where(
                PaymentLink.external_reference == external_reference,
                PaymentLink.provider == provider,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        return {"status": "not_found", "external_reference": external_reference}

    store = await _load_store(db, link.store_id)
    _, cfg = await _resolve_provider_and_cfg(db, store, provider)
    verified, signature_status = verify_provider_webhook_signature(provider, payload, dict(request.headers), cfg)
    if not verified and signature_status not in {"unsigned", "not_applicable"}:
        await record_workflow_event(
            db,
            workflow_type="payment_link_webhook",
            status="rejected",
            provider=provider,
            tenant_id=link.store_id,
            external_event_id=event_id,
            message_id=str(link.id),
            signature_status=signature_status,
        )
        raise HTTPException(status_code=401, detail="Signature webhook invalide")

    dedup_key = f"payment-link:{provider}:{event_id}"
    acquired = await lock_service.acquire(dedup_key, ttl=86400)
    if not acquired:
        return {"status": "duplicate_ignored", "event_id": event_id}

    normalized_status = _normalize_webhook_status(
        data.get("status") or data.get("payment_status") or data.get("result") or data.get("Response") or ""
    )
    if normalized_status == "pending":
        # fallback provider-side verify for ambiguous payloads
        adapter = PaymentFactory.get(provider, cfg)
        verify_result = await adapter.verify_payment(external_reference)
        normalized_status = verify_result.get("status", "pending")
        payload_snapshot = {"payload": data, "verify": verify_result}
    else:
        payload_snapshot = {"payload": data}

    _apply_payment_status(link, normalized_status, provider_payload=payload_snapshot)
    await db.commit()
    await record_workflow_event(
        db,
        workflow_type="payment_link_webhook",
        status=normalized_status,
        provider=provider,
        tenant_id=link.store_id,
        external_event_id=event_id,
        message_id=str(link.id),
        signature_status=signature_status,
    )
    return {"status": "processed", "payment_link_id": link.id, "new_status": normalized_status}


async def _generate_invoice_background(payment_link_id: int, store_id: int) -> None:
    try:
        async with AsyncSessionLocal() as db:
            link = await _get_link_or_none(db, payment_link_id, store_id)
            if link is None:
                return
            store = await _load_store(db, store_id)
            await create_and_save_invoice(db=db, payment_link=link, store=store)
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("invoice background generation failed payment_link_id=%s error=%s", payment_link_id, exc)


async def _get_link_or_none(db: AsyncSession, link_id: int, store_id: int) -> PaymentLink | None:
    return (
        await db.execute(
            select(PaymentLink).where(PaymentLink.id == link_id, PaymentLink.store_id == store_id)
        )
    ).scalar_one_or_none()


async def _get_link_or_404(db: AsyncSession, link_id: int, store_id: int) -> PaymentLink:
    link = await _get_link_or_none(db, link_id, store_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Lien de paiement non trouvé")
    return link


def _to_response(link: PaymentLink) -> PaymentLinkResponse:
    return PaymentLinkResponse(
        id=link.id,
        provider=link.provider,
        url=link.url,
        amount=float(link.amount),
        subtotal_amount=float(link.subtotal_amount) if link.subtotal_amount is not None else None,
        tax_amount=float(link.tax_amount) if link.tax_amount is not None else None,
        discount_amount=float(link.discount_amount) if link.discount_amount is not None else None,
        promotion_codes=link.promotion_codes,
        promotion_breakdown=link.promotion_breakdown,
        currency=link.currency,
        country_code=link.country_code,
        description=link.description,
        status=link.status,
        invoice_url=link.invoice_url,
        invoice_number=link.invoice_number,
        channel=link.channel,
        customer_name=link.customer_name,
        customer_phone=link.customer_phone,
        customer_email=link.customer_email,
        tax_breakdown=link.tax_breakdown,
        refunded_amount=float(link.refunded_amount) if link.refunded_amount is not None else None,
        failure_reason=link.failure_reason,
        last_verified_at=link.last_verified_at,
        created_at=link.created_at,
    )


def _apply_payment_status(link: PaymentLink, new_status: str | None, *, provider_payload: dict[str, Any] | None = None) -> None:
    status = (new_status or "pending").lower()
    if status == "paid":
        if link.status != "paid":
            link.paid_at = datetime.now(UTC)
        link.status = "paid"
        link.failure_reason = None
    elif status in {"failed", "expired"}:
        link.status = status
        link.failure_reason = status
    elif status == "refunded":
        link.status = "refunded"
        link.refunded_amount = link.amount
    elif status == "cancelled":
        link.status = "cancelled"
        link.cancelled_at = datetime.now(UTC)
    else:
        link.status = "pending"
    link.last_verified_at = datetime.now(UTC)
    if provider_payload is not None:
        link.provider_payload = provider_payload


def _normalize_webhook_status(raw_status: Any) -> str:
    raw = str(raw_status or "").strip().upper()
    if raw in {"PAID", "SUCCESS", "COMPLETED", "APPROVED", "00", "CAPTURED"}:
        return "paid"
    if raw in {"REFUNDED", "REFUND", "PARTIALLY_REFUNDED", "PARTIAL_REFUND"}:
        return "refunded"
    if raw in {"FAILED", "DECLINED", "ERROR", "KO"}:
        return "failed"
    if raw in {"CANCELLED", "CANCELED", "VOIDED"}:
        return "cancelled"
    if raw in {"EXPIRED"}:
        return "expired"
    return "pending"


def _parse_payload(payload: bytes) -> dict[str, Any]:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        from urllib.parse import parse_qs
        parsed = parse_qs(payload.decode(errors="ignore"))
        return {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}


def _extract_external_reference(data: dict[str, Any]) -> str:
    candidates = [
        data.get("id"),
        data.get("payment_id"),
        data.get("paymentRef"),
        data.get("payment_ref"),
        data.get("transaction_id"),
        data.get("reference"),
        data.get("checkout_session_id"),
        data.get("link_id"),
        data.get("oid"),
    ]
    for candidate in candidates:
        if candidate:
            return str(candidate)
    return ""


def _extract_event_id(data: dict[str, Any], provider: str, external_reference: str) -> str:
    candidates = [
        data.get("event_id"),
        data.get("id"),
        data.get("event"),
        data.get("payment_intent"),
        data.get("transaction_id"),
    ]
    for candidate in candidates:
        if candidate:
            return f"{provider}:{candidate}"
    return f"{provider}:{external_reference}:{data.get('status', 'unknown')}"


def _build_message(link: PaymentLink, custom_message: str | None = None) -> str:
    greeting = custom_message or f"Bonjour{' ' + link.customer_name if link.customer_name else ''} 👋"
    return (
        f"{greeting}\n\n"
        f"💳 Lien de paiement : {link.url or 'Paiement manuel'}\n"
        f"📋 Référence : {link.invoice_number or link.id}\n"
        f"💰 Montant : {float(link.amount):.2f} {link.currency}"
    )


async def _send_via_whatsapp(store: Store | None, recipient: str, message: str) -> dict[str, Any]:
    try:
        import httpx

        access_token = None
        phone_number_id = None
        if store is not None:
            if getattr(store, "whatsapp_access_token_enc", None):
                try:
                    access_token = settings.decrypt(store.whatsapp_access_token_enc)
                except Exception:  # noqa: BLE001
                    access_token = None
            phone_number_id = getattr(store, "whatsapp_phone_number_id", None)
        access_token = access_token or settings.WHATSAPP_ACCESS_TOKEN
        phone_number_id = phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID
        if not access_token or not phone_number_id:
            return {"warning": "WhatsApp non configuré"}
        phone = recipient.strip().replace("+", "").replace(" ", "").replace("-", "")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"https://graph.facebook.com/v19.0/{phone_number_id}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "to": phone,
                    "type": "text",
                    "text": {"body": message},
                },
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            return {"status": "sent", "whatsapp_message_id": response.json().get("messages", [{}])[0].get("id")}
    except Exception as exc:  # noqa: BLE001
        logger.error("send whatsapp failed: %s", exc)
        return {"error": str(exc)}
