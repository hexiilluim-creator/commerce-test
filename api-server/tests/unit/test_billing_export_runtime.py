from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.billing_export import (
    InvoiceLine,
    export_invoice_csv,
    export_invoice_pdf,
    handle_stripe_webhook_reconciliation,
    reconcile_stripe_payments,
)


@pytest.fixture
def invoice_data():
    return dict(
        tenant_id=7,
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 31, tzinfo=UTC),
        lines=[InvoiceLine("2026-01-02", "Top up", 2, 10, 20, 12.5)],
        totals={"credits_used": 20, "credits_purchased": 50, "amount_dt": 12.5},
    )


def test_export_invoice_csv(invoice_data):
    raw, filename = export_invoice_csv(**invoice_data)
    text = raw.decode("utf-8")
    assert filename == "invoice_7_20260101_20260131.csv"
    assert "tenant_id" in text and "Top up" in text
    assert "TOTAL_CREDITS_USED,20" in text
    assert "12.500" in text


def test_export_invoice_pdf_reportlab(invoice_data):
    raw, filename = export_invoice_pdf(store_name="Demo", **invoice_data)
    assert filename.endswith(".pdf")
    assert raw.startswith(b"%PDF")
    assert len(raw) > 500


def test_export_invoice_pdf_text_fallback(invoice_data, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def import_without_reportlab(name, *args, **kwargs):
        if name.startswith("reportlab"):
            raise ImportError("reportlab intentionally unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_reportlab)
    raw, filename = export_invoice_pdf(store_name="Demo", **invoice_data)
    assert filename.endswith(".txt")
    assert b"AutoCommerce Facture" in raw
    assert b"TOTAL_DT" in raw


@pytest.mark.asyncio
async def test_reconcile_without_stripe_key_returns_warning(monkeypatch):
    session = AsyncMock()
    row_result = MagicMock()
    row_result.mappings.return_value.all.return_value = [{"reference_id": "pi_1"}]
    session.execute.return_value = row_result
    settings = SimpleNamespace(STRIPE_SECRET_KEY=None)
    with patch("config.settings", settings):
        result = await reconcile_stripe_payments(session, tenant_id=7)
    assert result["matched"] == 0
    assert "absent" in result["warning"]


@pytest.mark.asyncio
async def test_reconcile_stripe_diff(monkeypatch):
    session = AsyncMock()
    row_result = MagicMock()
    row_result.mappings.return_value.all.return_value = [
        {"reference_id": "pi_match"}, {"reference_id": "pi_missing"}
    ]
    session.execute.return_value = row_result
    settings = SimpleNamespace(STRIPE_SECRET_KEY="sk_test")
    fake_stripe = SimpleNamespace()
    fake_stripe.PaymentIntent = SimpleNamespace(list=MagicMock(return_value=SimpleNamespace(auto_paging_iter=lambda: [{"id": "pi_match"}, {"id": "pi_extra"}])))
    with patch("config.settings", settings), patch.dict("sys.modules", {"stripe": fake_stripe}):
        result = await reconcile_stripe_payments(session, tenant_id=7)
    assert result["matched"] == 1
    assert result["missing"] == ["pi_missing"]
    assert result["extra"] == ["pi_extra"]


@pytest.mark.asyncio
async def test_stripe_webhook_ignored_and_missing_metadata():
    ignored = await handle_stripe_webhook_reconciliation({"type": "charge.failed"})
    assert ignored["handled"] is False
    missing = await handle_stripe_webhook_reconciliation({"type": "payment_intent.succeeded", "data": {"object": {"id": "pi"}}})
    assert missing["reason"] == "metadata_missing_tenant_or_pi"


@pytest.mark.asyncio
async def test_stripe_webhook_idempotent_and_credit_purchase():
    event = {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_123", "amount": 2500, "currency": "eur", "metadata": {"tenant_id": "7", "pack_id": "starter_50"}}}}
    with patch("services.idempotency.check_idempotency", new=AsyncMock(return_value=True), create=True):
        result = await handle_stripe_webhook_reconciliation(event)
    assert result["idempotent"] is True
    with patch("services.idempotency.check_idempotency", new=AsyncMock(return_value=False), create=True), \
         patch("services.credit_ledger.purchase_top_up", new=AsyncMock(return_value={"credits": 50})):
        result = await handle_stripe_webhook_reconciliation(event)
    assert result["credited"] if "credited" in result else result["credit_result"] == {"credits": 50}
    assert result["amount"] == 25.0


@pytest.mark.asyncio
async def test_stripe_webhook_audit_only():
    event = {"type": "charge.succeeded", "data": {"object": {"id": "ch_1", "amount": 100, "metadata": {"tenant_id": "7"}}}}
    with patch("services.idempotency.check_idempotency", new=AsyncMock(return_value=False), create=True):
        result = await handle_stripe_webhook_reconciliation(event)
    assert result["handled"] is True
    assert result["credited"] is False
    assert result["amount"] == 1.0
