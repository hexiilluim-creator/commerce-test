from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.v1.payment_links import (
    CreatePaymentLinkRequest,
    PaymentLinkResponse,
    _decrypt_cfg,
    _get_store_id,
    _resolve_provider_and_cfg,
)


def test_create_payment_link_request_normalizes_and_validates():
    body = CreatePaymentLinkRequest(amount=10, currency="eur", provider="STRIPE", country_code="tn")
    assert body.currency == "EUR"
    assert body.provider == "stripe"
    assert body.country_code == "TN"
    with pytest.raises(ValidationError):
        CreatePaymentLinkRequest(provider="unknown", amount=10)
    with pytest.raises(ValidationError):
        CreatePaymentLinkRequest()


def test_create_payment_link_accepts_order_without_amount():
    body = CreatePaymentLinkRequest(order_id=12, description="Order")
    assert body.order_id == 12
    assert body.amount is None


def test_decrypt_cfg_only_decrypts_enc_values():
    with patch("api.v1.payment_links.settings", SimpleNamespace(decrypt=lambda v: f"plain-{v}")):
        cfg = _decrypt_cfg({"api_key": "enc_secret", "enabled": True, "nested": 3})
    assert cfg == {"api_key": "plain-secret", "enabled": True, "nested": 3}


def test_get_store_id_requires_tenant():
    with patch("api.v1.payment_links._sid", return_value=None):
        with pytest.raises(HTTPException) as exc:
            _get_store_id()
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_resolve_provider_cash_and_configured_provider():
    db = AsyncMock()
    store = SimpleNamespace(country="TN", payment_config={"stripe": {"api_key": "enc_key"}})
    provider, cfg = await _resolve_provider_and_cfg(db, store, "cash")
    assert provider == "cash" and cfg == {}
    with patch("api.v1.payment_links.settings", SimpleNamespace(decrypt=lambda v: "key")):
        provider, cfg = await _resolve_provider_and_cfg(db, store, "stripe")
    assert provider == "stripe" and cfg["api_key"] == "key"


@pytest.mark.asyncio
async def test_resolve_provider_rejects_unconfigured_and_defaults_cash():
    db = AsyncMock()
    store = SimpleNamespace(country="TN", payment_config={})
    with pytest.raises(HTTPException) as exc:
        await _resolve_provider_and_cfg(db, store, "stripe")
    assert exc.value.status_code == 400
    provider, cfg = await _resolve_provider_and_cfg(db, store, None)
    assert provider == "cash" and cfg == {}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("SUCCESS", "paid"), ("00", "paid"), ("PARTIAL_REFUND", "refunded"), ("KO", "failed"), ("CANCELED", "cancelled"), ("EXPIRED", "expired"), ("unknown", "pending")],
)
def test_webhook_status_normalization(raw, expected):
    from api.v1.payment_links import _normalize_webhook_status
    assert _normalize_webhook_status(raw) == expected


def test_payload_parsing_json_and_form_encoded():
    from api.v1.payment_links import _parse_payload
    assert _parse_payload(b'{"id":"x","status":"PAID"}') == {"id": "x", "status": "PAID"}
    assert _parse_payload(b"id=x&status=PAID&tag=a&tag=b") == {"id": "x", "status": "PAID", "tag": ["a", "b"]}


def test_reference_event_and_message_helpers():
    from api.v1.payment_links import _build_message, _extract_event_id, _extract_external_reference
    link = SimpleNamespace(id=9, customer_name="Amine", url="https://pay.test/9", invoice_number="INV-9", amount=12.5, currency="TND")
    assert _extract_external_reference({"transaction_id": "tx-1"}) == "tx-1"
    assert _extract_external_reference({}) == ""
    assert _extract_event_id({"event_id": "evt-1"}, "stripe", "tx") == "stripe:evt-1"
    assert _extract_event_id({"status": "paid"}, "cash", "tx") == "cash:tx:paid"
    message = _build_message(link)
    assert "Bonjour Amine" in message and "12.50 TND" in message
    assert _build_message(link, "Custom") .startswith("Custom")


def test_apply_payment_status_transitions():
    from api.v1.payment_links import _apply_payment_status
    link = SimpleNamespace(status="pending", amount=25.0, failure_reason=None, refunded_amount=None, paid_at=None, cancelled_at=None, last_verified_at=None, provider_payload=None)
    _apply_payment_status(link, "paid", provider_payload={"id": "x"})
    assert link.status == "paid" and link.failure_reason is None and link.paid_at is not None
    _apply_payment_status(link, "refunded")
    assert link.status == "refunded" and link.refunded_amount == 25.0
    _apply_payment_status(link, "cancelled")
    assert link.status == "cancelled" and link.cancelled_at is not None
    _apply_payment_status(link, "failed")
    assert link.failure_reason == "failed"


@pytest.mark.asyncio
async def test_get_link_helpers_return_entity_or_404():
    from api.v1.payment_links import _get_link_or_none, _get_link_or_404
    entity = SimpleNamespace(id=4)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: entity))
    assert await _get_link_or_none(db, 4, 8) is entity
    assert await _get_link_or_404(db, 4, 8) is entity

    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None))
    assert await _get_link_or_none(db, 4, 8) is None
    with pytest.raises(HTTPException) as exc:
        await _get_link_or_404(db, 4, 8)
    assert exc.value.status_code == 404


def test_payment_link_response_maps_optional_financial_fields():
    from api.v1.payment_links import _to_response
    link = SimpleNamespace(
        id=4, provider="cash", url=None, amount=12.5, subtotal_amount=None,
        tax_amount=1.5, discount_amount=None, promotion_codes=None,
        promotion_breakdown=None, currency="TND", country_code="TN",
        description="part", status="pending", invoice_url=None,
        invoice_number="INV-4", channel="whatsapp", customer_name=None,
        customer_phone=None, customer_email=None, tax_breakdown=[{"vat": 1.5}],
        refunded_amount=None, failure_reason=None, last_verified_at=None,
        created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    result = _to_response(link)
    assert result.id == 4 and result.amount == 12.5
    assert result.tax_amount == 1.5 and result.url is None


def test_apply_payment_status_covers_failed_expired_pending_and_idempotent_paid():
    from api.v1.payment_links import _apply_payment_status
    link = SimpleNamespace(status="paid", amount=10, failure_reason=None,
                           refunded_amount=None, paid_at=None, cancelled_at=None,
                           last_verified_at=None, provider_payload=None)
    _apply_payment_status(link, "paid", provider_payload={"state": "paid"})
    assert link.status == "paid" and link.paid_at is None
    assert link.provider_payload == {"state": "paid"}
    _apply_payment_status(link, "expired")
    assert link.status == "expired" and link.failure_reason == "expired"
    _apply_payment_status(link, "unknown")
    assert link.status == "pending"


def test_external_reference_checks_all_supported_provider_keys():
    from api.v1.payment_links import _extract_external_reference
    for key in ("id", "payment_id", "paymentRef", "payment_ref", "transaction_id", "reference", "checkout_session_id", "link_id", "oid"):
        assert _extract_external_reference({key: 123}) == "123"
    assert _extract_external_reference({"id": 0, "oid": "last"}) == "last"


@pytest.mark.asyncio
async def test_payment_links_list_and_analytics_apply_filters_and_totals():
    from unittest.mock import MagicMock, patch
    import api.v1.payment_links as module
    from datetime import UTC, datetime
    link = SimpleNamespace(id=4, provider="cash", url="https://pay.test/4", amount=12.5, subtotal_amount=10.0, tax_amount=2.5, discount_amount=0, promotion_codes=None, promotion_breakdown=None, currency="TND", country_code="TN", description="part", status="paid", invoice_url=None, invoice_number="INV-4", channel="manual", customer_name="A", customer_phone=None, customer_email=None, tax_breakdown=[], refunded_amount=0, failure_reason=None, last_verified_at=None, created_at=datetime(2026, 8, 14, tzinfo=UTC))
    listed = MagicMock(); listed.scalars.return_value.all.return_value = [link]
    counted = MagicMock(); counted.scalar_one.return_value = 3
    db = AsyncMock(); db.execute.side_effect = [listed, counted]
    with patch.object(module, "_sid", return_value=3):
        result = await module.list_payment_links(page=2, limit=2, status="paid", provider="cash", db=db)
    assert result["total"] == 3 and result["page"] == 2 and result["pages"] == 2 and result["items"][0]["id"] == 4
    status_rows = MagicMock(); status_rows.__iter__.return_value = [SimpleNamespace(status="paid", count=2, total=25), SimpleNamespace(status="pending", count=1, total=None)]
    provider_rows = MagicMock(); provider_rows.__iter__.return_value = [SimpleNamespace(provider="cash", count=3)]
    db.execute.side_effect = [status_rows, provider_rows]
    with patch.object(module, "_sid", return_value=3):
        analytics = await module.payment_links_analytics(db)
    assert analytics["revenue_paid"] == 25.0 and analytics["pending_count"] == 1 and analytics["by_provider"] == {"cash": 3}


@pytest.mark.asyncio
async def test_accounting_export_returns_csv_stream():
    from unittest.mock import AsyncMock, patch
    import api.v1.payment_links as module
    db = AsyncMock()
    with patch.object(module, "_sid", return_value=3), patch.object(module, "export_accounting_csv", new=AsyncMock(return_value="id,status\n1,paid\n")):
        response = await module.accounting_export(db)
    assert response.media_type == "text/csv" and "accounting_export_3.csv" in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_send_payment_link_email_marks_channel_and_sent_at():
    from unittest.mock import AsyncMock, patch
    import api.v1.payment_links as module
    link = SimpleNamespace(id=4, invoice_number="INV-4", customer_name="A", url="https://pay.test/4", amount=12.5, currency="TND", channel=None, sent_at=None)
    store = SimpleNamespace(name="Demo")
    db = AsyncMock()
    with patch.object(module, "_get_store_id", return_value=3), patch.object(module, "_get_link_or_404", new=AsyncMock(return_value=link)), patch.object(module, "_load_store", new=AsyncMock(return_value=store)), patch.object(module, "send_invoice_email", new=AsyncMock()) as send_email:
        result = await module.send_payment_link(4, module.SendPaymentLinkRequest(channel="email", recipient="a@example.com"), db)
    assert result == {"success": True, "status": "sent", "channel": "email"} and link.channel == "email" and link.sent_at is not None
    send_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_payment_link_applies_provider_status():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.payment_links as module
    link = SimpleNamespace(id=4, store_id=3, provider="cash", external_reference="ref-4", status="pending", amount=10, failure_reason=None, refunded_amount=None, paid_at=None, cancelled_at=None, last_verified_at=None, provider_payload=None)
    store = SimpleNamespace(country="TN", payment_config={})
    adapter = MagicMock(); adapter.verify_payment = AsyncMock(return_value={"status": "paid", "id": "ref-4"})
    db = AsyncMock()
    with patch.object(module, "_get_store_id", return_value=3), patch.object(module, "_get_link_or_404", new=AsyncMock(return_value=link)), patch.object(module, "_load_store", new=AsyncMock(return_value=store)), patch.object(module.PaymentFactory, "get", return_value=adapter):
        result = await module.verify_payment_link(4, db)
    assert result["status"] == "paid" and link.status == "paid"


@pytest.mark.asyncio
async def test_refund_payment_link_updates_partial_refund_and_credit_note():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.payment_links as module
    link = SimpleNamespace(id=4, store_id=3, provider="cash", external_reference="ref-4", status="paid", amount=100, refunded_amount=0, last_verified_at=None, provider_payload={})
    store = SimpleNamespace(country="TN", payment_config={})
    adapter = MagicMock(); adapter.refund_payment = AsyncMock(return_value={"refund_id": "r1"})
    db = AsyncMock()
    with patch.object(module, "_get_store_id", return_value=3), patch.object(module, "_get_link_or_404", new=AsyncMock(return_value=link)), patch.object(module, "_load_store", new=AsyncMock(return_value=store)), patch.object(module.PaymentFactory, "get", return_value=adapter), patch.object(module, "create_credit_note_for_payment_link", new=AsyncMock(return_value={"number": "CN-1"})):
        result = await module.refund_payment_link(4, module.RefundPaymentLinkRequest(amount=25, reason="duplicate"), db)
    assert result["credit_note"]["number"] == "CN-1" and link.refunded_amount == 25 and link.status == "paid"


@pytest.mark.asyncio
async def test_cancel_payment_link_calls_provider_and_rejects_paid_link():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.payment_links as module
    paid = SimpleNamespace(id=4, store_id=3, status="paid")
    with patch.object(module, "_get_store_id", return_value=3), patch.object(module, "_get_link_or_404", new=AsyncMock(return_value=paid)):
        with pytest.raises(HTTPException) as exc:
            await module.cancel_payment_link(4, AsyncMock())
    assert exc.value.status_code == 400
    link = SimpleNamespace(id=4, store_id=3, provider="cash", external_reference="ref-4", status="pending", cancelled_at=None, last_verified_at=None, provider_payload={})
    store = SimpleNamespace(country="TN", payment_config={})
    adapter = MagicMock(); adapter.cancel_payment = AsyncMock(return_value={"cancelled": True})
    db = AsyncMock()
    with patch.object(module, "_get_store_id", return_value=3), patch.object(module, "_get_link_or_404", new=AsyncMock(return_value=link)), patch.object(module, "_load_store", new=AsyncMock(return_value=store)), patch.object(module.PaymentFactory, "get", return_value=adapter):
        result = await module.cancel_payment_link(4, db)
    assert result["cancel"]["cancelled"] is True and link.status == "cancelled"


class _WebhookRequest:
    def __init__(self, payload: bytes, headers=None):
        self._payload = payload
        self.headers = headers or {}

    async def body(self):
        return self._payload


@pytest.mark.asyncio
async def test_payment_link_webhook_rejects_unknown_and_ignores_missing_reference():
    import api.v1.payment_links as module
    with pytest.raises(HTTPException) as exc:
        await module.payment_link_webhook("unknown", _WebhookRequest(b"{}"), AsyncMock())
    assert exc.value.status_code == 404
    result = await module.payment_link_webhook("cash", _WebhookRequest(b'{"status":"paid"}'), AsyncMock())
    assert result == {"status": "ignored", "reason": "no_reference"}


@pytest.mark.asyncio
async def test_payment_link_webhook_returns_not_found_for_unknown_reference():
    from unittest.mock import MagicMock, patch
    import api.v1.payment_links as module
    db = AsyncMock(); result = MagicMock(); result.scalar_one_or_none.return_value = None; db.execute.return_value = result
    with patch.object(module, "verify_provider_webhook_signature", return_value=(True, "valid")):
        response = await module.payment_link_webhook("cash", _WebhookRequest(b'{"id":"missing","status":"paid"}'), db)
    assert response["status"] == "not_found" and response["external_reference"] == "missing"


@pytest.mark.asyncio
async def test_payment_link_webhook_rejects_invalid_signature():
    from unittest.mock import MagicMock, AsyncMock, patch
    import api.v1.payment_links as module
    link = SimpleNamespace(id=4, store_id=3, provider="cash", external_reference="ref-4")
    db = AsyncMock(); result = MagicMock(); result.scalar_one_or_none.return_value = link; db.execute.return_value = result
    with patch.object(module, "_load_store", new=AsyncMock(return_value=SimpleNamespace(country="TN", payment_config={}))), patch.object(module, "_resolve_provider_and_cfg", new=AsyncMock(return_value=("cash", {}))), patch.object(module, "verify_provider_webhook_signature", return_value=(False, "invalid")), patch.object(module, "record_workflow_event", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await module.payment_link_webhook("cash", _WebhookRequest(b'{"id":"ref-4","status":"paid"}'), db)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_payment_link_webhook_ignores_duplicate_event():
    from unittest.mock import MagicMock, AsyncMock, patch
    import api.v1.payment_links as module
    link = SimpleNamespace(id=4, store_id=3, provider="cash", external_reference="ref-4")
    db = AsyncMock(); result = MagicMock(); result.scalar_one_or_none.return_value = link; db.execute.return_value = result
    with patch.object(module, "_load_store", new=AsyncMock(return_value=SimpleNamespace(country="TN", payment_config={}))), patch.object(module, "_resolve_provider_and_cfg", new=AsyncMock(return_value=("cash", {}))), patch.object(module, "verify_provider_webhook_signature", return_value=(True, "valid")), patch.object(module.lock_service, "acquire", new=AsyncMock(return_value=False)):
        response = await module.payment_link_webhook("cash", _WebhookRequest(b'{"id":"ref-4","status":"paid"}'), db)
    assert response["status"] == "duplicate_ignored"


@pytest.mark.asyncio
async def test_payment_link_webhook_processes_paid_event_and_commits():
    from unittest.mock import MagicMock, AsyncMock, patch
    import api.v1.payment_links as module
    link = SimpleNamespace(id=4, store_id=3, provider="cash", external_reference="ref-4", status="pending", amount=20, failure_reason=None, refunded_amount=None, paid_at=None, cancelled_at=None, last_verified_at=None, provider_payload=None)
    db = AsyncMock(); result = MagicMock(); result.scalar_one_or_none.return_value = link; db.execute.return_value = result
    with patch.object(module, "_load_store", new=AsyncMock(return_value=SimpleNamespace(country="TN", payment_config={}))), patch.object(module, "_resolve_provider_and_cfg", new=AsyncMock(return_value=("cash", {}))), patch.object(module, "verify_provider_webhook_signature", return_value=(True, "valid")), patch.object(module.lock_service, "acquire", new=AsyncMock(return_value=True)), patch.object(module, "record_workflow_event", new=AsyncMock()):
        response = await module.payment_link_webhook("cash", _WebhookRequest(b'{"id":"ref-4","status":"paid"}'), db)
    assert response == {"status": "processed", "payment_link_id": 4, "new_status": "paid"} and link.status == "paid"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_payment_link_manual_amount_runs_promotions_taxes_and_provider():
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.payment_links as module
    body = module.CreatePaymentLinkRequest(amount=100, currency="eur", provider="cash", description="Service", customer_email="a@example.com", coupon_codes=["WELCOME"])
    store = SimpleNamespace(id=3, country="TN", default_tax_country="TN", payment_config={}, invoice_prefix="INV", name="Demo")
    promo = SimpleNamespace(items=[{"name": "Service", "qty": 1, "unit_price": 90}], discount_amount=10, applied_coupon_codes=["WELCOME"], applied_promotions=[{"code": "WELCOME", "amount": 10}])
    tax = SimpleNamespace(total_amount=99, subtotal_amount=90, tax_amount=9, breakdown=[{"rate": 10}], country_code="TN")
    adapter = MagicMock(); adapter.create_payment_link = AsyncMock(return_value={"url": "https://pay.test/new", "id": "ext-1"})
    payment_link = SimpleNamespace(id=7, store_id=3, order_id=None, provider="cash", url="https://pay.test/new", amount=99, subtotal_amount=90, tax_amount=9, discount_amount=10, promotion_codes=["WELCOME"], promotion_breakdown=[{"code": "WELCOME", "amount": 10}], currency="EUR", country_code="TN", tax_breakdown=[{"rate": 10}], description="Service", status="pending", invoice_url=None, invoice_number="INV-7", channel="manual", customer_name=None, customer_email="a@example.com", customer_phone=None, refunded_amount=None, failure_reason=None, last_verified_at=None, created_at=datetime(2026, 8, 14, tzinfo=UTC))
    db = SimpleNamespace(add=MagicMock(), flush=AsyncMock(), commit=AsyncMock(), refresh=AsyncMock())
    background = MagicMock()
    with patch.object(module, "_get_store_id", return_value=3), patch.object(module, "_load_store", new=AsyncMock(return_value=store)), patch.object(module, "_resolve_provider_and_cfg", new=AsyncMock(return_value=("cash", {}))), patch.object(module, "apply_promotions_to_items", new=AsyncMock(return_value=promo)), patch.object(module, "calculate_manual_amount_taxes", new=AsyncMock(return_value=tax)), patch.object(module.PaymentFactory, "get", return_value=adapter), patch.object(module, "generate_invoice_number", return_value="INV-7"), patch.object(module, "record_promotion_usage", new=AsyncMock()), patch.object(module, "PaymentLink", return_value=payment_link):
        response = await module.create_payment_link(body, background, db)
    assert response.id == 7 and response.amount == 99 and response.currency == "EUR" and response.status == "pending"
    db.commit.assert_awaited_once(); background.add_task.assert_called_once()


@pytest.mark.asyncio
async def test_create_payment_link_provider_failure_returns_502():
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.payment_links as module
    body = module.CreatePaymentLinkRequest(amount=20, provider="cash")
    store = SimpleNamespace(id=3, country="TN", default_tax_country="TN", payment_config={}, invoice_prefix="INV", name="Demo")
    promo = SimpleNamespace(items=[{"name": "Paiement en ligne", "qty": 1, "unit_price": 20}], discount_amount=0, applied_coupon_codes=[], applied_promotions=[])
    tax = SimpleNamespace(total_amount=20, subtotal_amount=20, tax_amount=0, breakdown=[], country_code="TN")
    adapter = MagicMock(); adapter.create_payment_link = AsyncMock(side_effect=RuntimeError("provider down"))
    db = SimpleNamespace(add=MagicMock(), flush=AsyncMock(), commit=AsyncMock(), refresh=AsyncMock())
    with patch.object(module, "_get_store_id", return_value=3), patch.object(module, "_load_store", new=AsyncMock(return_value=store)), patch.object(module, "_resolve_provider_and_cfg", new=AsyncMock(return_value=("cash", {}))), patch.object(module, "apply_promotions_to_items", new=AsyncMock(return_value=promo)), patch.object(module, "calculate_manual_amount_taxes", new=AsyncMock(return_value=tax)), patch.object(module.PaymentFactory, "get", return_value=adapter):
        with pytest.raises(HTTPException) as exc:
            await module.create_payment_link(body, MagicMock(), db)
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_create_payment_link_from_order_uses_order_taxes_and_promotions():
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.payment_links as module
    body = module.CreatePaymentLinkRequest(order_id=8, provider="cash", description="Commande")
    store = SimpleNamespace(id=3, country="TN", default_tax_country="TN", payment_config={}, invoice_prefix="INV", name="Demo")
    order = SimpleNamespace(id=8, items=[{"name": "Part", "qty": 1, "unit_price": 50}], promotion_codes=[], customer_id=2, discount_amount=0, promotion_breakdown=[])
    promo = SimpleNamespace(items=order.items, discount_amount=0, applied_coupon_codes=[], applied_promotions=[])
    tax = SimpleNamespace(total_amount=55, subtotal_amount=50, tax_amount=5, breakdown=[{"rate": 10}], country_code="TN")
    adapter = MagicMock(); adapter.create_payment_link = AsyncMock(return_value={"url": "https://pay.test/order", "id": "ext-order"})
    payment_link = SimpleNamespace(id=9, store_id=3, order_id=8, provider="cash", url="https://pay.test/order", amount=55, subtotal_amount=50, tax_amount=5, discount_amount=0, promotion_codes=[], promotion_breakdown=[], currency="TND", country_code="TN", tax_breakdown=[{"rate": 10}], description="Commande", status="pending", invoice_url=None, invoice_number="INV-9", channel="manual", customer_name=None, customer_email=None, customer_phone=None, refunded_amount=None, failure_reason=None, last_verified_at=None, created_at=datetime(2026, 8, 14, tzinfo=UTC))
    db = SimpleNamespace(add=MagicMock(), flush=AsyncMock(), commit=AsyncMock(), refresh=AsyncMock())
    with patch.object(module, "_get_store_id", return_value=3), patch.object(module, "_load_store", new=AsyncMock(return_value=store)), patch.object(module, "_resolve_provider_and_cfg", new=AsyncMock(return_value=("cash", {}))), patch.object(module, "_load_order_for_store", new=AsyncMock(return_value=order)), patch.object(module, "apply_promotions_to_items", new=AsyncMock(return_value=promo)), patch.object(module, "calculate_order_taxes", new=AsyncMock(return_value=tax)), patch.object(module.PaymentFactory, "get", return_value=adapter), patch.object(module, "generate_invoice_number", return_value="INV-9"), patch.object(module, "record_promotion_usage", new=AsyncMock()), patch.object(module, "PaymentLink", return_value=payment_link):
        response = await module.create_payment_link(body, MagicMock(), db)
    assert response.id == 9 and response.amount == 55 and order.total_amount == 55 and order.currency == "TND"


@pytest.mark.asyncio
async def test_download_invoice_requires_invoice_number():
    from unittest.mock import AsyncMock, patch
    import api.v1.payment_links as module
    link = SimpleNamespace(id=4, invoice_number=None)
    with patch.object(module, "_get_store_id", return_value=3), patch.object(module, "_get_link_or_404", new=AsyncMock(return_value=link)):
        with pytest.raises(HTTPException) as exc:
            await module.download_invoice(4, AsyncMock())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_download_invoice_generates_missing_pdf_and_returns_file():
    from unittest.mock import AsyncMock, patch
    import api.v1.payment_links as module
    link = SimpleNamespace(id=4, invoice_number="INV-4", invoice_pdf_path=None, invoice_url=None)
    store = SimpleNamespace(name="Demo")
    db = AsyncMock()
    with patch.object(module, "_get_store_id", return_value=3), patch.object(module, "_get_link_or_404", new=AsyncMock(return_value=link)), patch.object(module, "_load_store", new=AsyncMock(return_value=store)), patch.object(module, "create_and_save_invoice", new=AsyncMock(return_value={"pdf_path": "/tmp/invoice-4.pdf"})), patch.object(module.os.path, "exists", return_value=True):
        response = await module.download_invoice(4, db)
    assert response.media_type == "application/pdf" and link.invoice_url.endswith("/invoice") and link.invoice_pdf_path == "/tmp/invoice-4.pdf"


@pytest.mark.asyncio
async def test_download_invoice_reports_missing_generated_file():
    from unittest.mock import AsyncMock, patch
    import api.v1.payment_links as module
    link = SimpleNamespace(id=4, invoice_number="INV-4", invoice_pdf_path=None, invoice_url=None)
    with patch.object(module, "_get_store_id", return_value=3), patch.object(module, "_get_link_or_404", new=AsyncMock(return_value=link)), patch.object(module, "_load_store", new=AsyncMock(return_value=SimpleNamespace(name="Demo"))), patch.object(module, "create_and_save_invoice", new=AsyncMock(return_value={"pdf_path": "/tmp/missing.pdf"})), patch.object(module.os.path, "exists", return_value=False):
        with pytest.raises(HTTPException) as exc:
            await module.download_invoice(4, AsyncMock())
    assert exc.value.status_code == 404
