from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import payment_router


def test_detect_country_and_currency_maps_supported_and_unknown_inputs():
    assert payment_router.detect_country_from_phone(" +216 98-765-432 ") == "TN"
    assert payment_router.detect_country_from_phone("0033612345678") == "FR"
    assert payment_router.detect_country_from_phone("0612345678") is None
    assert payment_router.detect_country_from_phone(None) is None
    assert payment_router.get_default_currency("tn") == "TND"
    assert payment_router.get_default_currency("unknown") == "USD"
    assert payment_router.get_default_currency(None) == "USD"


def test_resolve_provider_uses_country_priority_and_fallbacks():
    assert payment_router.resolve_provider_with_fallback("TN", {"cash": {}}) == "cash"
    assert payment_router.resolve_provider_with_fallback("TN", {"stripe": {}, "flouci": {}}) == "flouci"
    assert payment_router.resolve_provider_with_fallback("FR", {"paypal": {}, "cash": {}}) == "paypal"
    assert payment_router.resolve_provider_with_fallback("XX", {"custom": {}}) == "custom"
    with pytest.raises(ValueError):
        payment_router.resolve_provider_with_fallback("TN", {})


def _db_context(store):
    db = AsyncMock()
    db.get.return_value = store
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=db)
    context.__aexit__ = AsyncMock(return_value=None)
    return db, context


@pytest.mark.asyncio
async def test_route_payment_returns_error_for_missing_store():
    db, context = _db_context(None)
    with patch("models.database.AsyncSessionLocal", return_value=context):
        result = await payment_router.route_payment(77, {"amount": 10})
    assert result["status"] == "error"
    assert "introuvable" in result["error"]


@pytest.mark.asyncio
async def test_route_payment_creates_link_with_country_currency():
    store = SimpleNamespace(country="TN", payment_config={"cash": {}})
    db, context = _db_context(store)
    provider = AsyncMock()
    provider.create_payment_link.return_value = {"payment_url": "https://pay.test/1", "ref": "r1"}
    factory = MagicMock()
    factory.get_provider.return_value = provider
    with patch("models.database.AsyncSessionLocal", return_value=context), patch(
        "services.payment_factory.PaymentFactory", return_value=factory
    ):
        result = await payment_router.route_payment(4, {"amount": 25, "order_id": "o1"})
    assert result == {
        "status": "created",
        "provider": "cash",
        "payment_url": "https://pay.test/1",
        "ref": "r1",
        "currency": "TND",
    }
    provider.create_payment_link.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_payment_converts_provider_errors_to_safe_response():
    store = SimpleNamespace(country="FR", payment_config={"stripe": {}})
    db, context = _db_context(store)
    factory = MagicMock()
    factory.get_provider.side_effect = RuntimeError("provider down")
    with patch("models.database.AsyncSessionLocal", return_value=context), patch(
        "services.payment_factory.PaymentFactory", return_value=factory
    ):
        result = await payment_router.route_payment(4, {"amount": 25})
    assert result["status"] == "error"
    assert "interne" in result["error"]


@pytest.mark.asyncio
async def test_status_and_callback_cover_unknown_and_paid_paths():
    store = SimpleNamespace(country="FR", payment_config={"stripe": {}})
    db, context = _db_context(store)
    provider = AsyncMock()
    provider.verify_payment.return_value = {"status": "paid", "amount": 42, "currency": "EUR"}
    factory = MagicMock()
    factory.get_provider.return_value = provider
    with patch("models.database.AsyncSessionLocal", return_value=context), patch(
        "services.payment_factory.PaymentFactory", return_value=factory
    ):
        status = await payment_router.get_payment_status(4, "r1")
        callback = await payment_router.handle_payment_callback(4, {"transaction_id": "r1"})
    assert status["status"] == "paid"
    assert callback["ok"] is True
    assert callback["ref"] == "r1"

    assert await payment_router.handle_payment_callback(4, {}) == {
        "ok": False,
        "error": "Référence de paiement manquante",
    }


@pytest.mark.asyncio
async def test_status_returns_unknown_for_missing_store_and_provider_exception():
    db, context = _db_context(None)
    with patch("models.database.AsyncSessionLocal", return_value=context):
        result = await payment_router.get_payment_status(4, "r1")
    assert result["status"] == "unknown"
    assert result["ref"] == "r1"

    store = SimpleNamespace(country="FR", payment_config={"stripe": {}})
    db, context = _db_context(store)
    factory = MagicMock()
    factory.get_provider.side_effect = RuntimeError("provider down")
    with patch("models.database.AsyncSessionLocal", return_value=context), patch(
        "services.payment_factory.PaymentFactory", return_value=factory
    ):
        result = await payment_router.get_payment_status(4, "r1")
    assert result["status"] == "unknown"
    assert result["ref"] == "r1"
