from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services.payment_factory import (
    CashProvider,
    PaymentFactory,
    _BaseProvider,
    _decrypt_config,
    _resolve_provider_name,
    verify_provider_webhook_signature,
)


def test_provider_resolution_and_decryption():
    assert _resolve_provider_name("TN", {"flouci": {"app_token": "x"}}) == "flouci"
    assert _resolve_provider_name("FR", {"stripe": {"api_key": "x"}}) == "stripe"
    assert _resolve_provider_name("TN", {}) == "cash"
    assert _resolve_provider_name(None, None) == "cash"
    with patch("services.payment_factory.settings", SimpleNamespace(decrypt=lambda value: "plain-" + value)):
        assert _decrypt_config({"api_key": "enc_secret", "mode": "test"}) == {"api_key": "plain-secret", "mode": "test"}
    with pytest.raises(HTTPException) as exc:
        _decrypt_config(None)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_base_and_cash_provider_behaviour():
    base = _BaseProvider()
    with pytest.raises(NotImplementedError):
        await base.create_payment_link(1, "TND")
    assert await base.refund_payment("ref", 2) == {"status": "manual_required", "provider": "base", "payment_ref": "ref", "amount": 2}
    cash = CashProvider()
    created = await cash.create_payment_link(10, "TND", description="Order", reference="O-1")
    assert created["provider"] == "cash" and created["method"] == "cash" and created["url"] is None
    assert (await cash.verify_payment("O-1"))["status"] == "pending_cash"


def test_factory_and_webhook_signature_dispatch():
    assert isinstance(PaymentFactory.get("cash", {}), CashProvider)
    with pytest.raises(HTTPException):
        PaymentFactory.get("unsupported", {})
    ok, reason = verify_provider_webhook_signature("cash", b"payload", {}, {})
    assert ok is True and reason == "not_applicable"
    with pytest.raises(HTTPException) as exc:
        verify_provider_webhook_signature("unknown", b"payload", {}, {})
    assert exc.value.status_code == 400
