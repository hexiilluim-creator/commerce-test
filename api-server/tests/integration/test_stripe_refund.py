from __future__ import annotations

import os
import sys
import types

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-32-characters-min")
os.environ.setdefault("ENCRYPTION_KEY", "HSs-6rKojKDyBDccY1QRXb-qF3hAfLJ6O9z_wpJdBMk=")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-characters-minimum")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token")

from services.payment_factory import StripeProvider


@pytest.mark.integration
@pytest.mark.payments
@pytest.mark.asyncio
async def test_stripe_refund_uses_payment_intent(monkeypatch):
    class SessionObj:
        payment_intent = "pi_test_123"

    class RefundObj:
        id = "re_test_123"

    checkout = types.SimpleNamespace(Session=types.SimpleNamespace(retrieve=lambda _payment_ref: SessionObj()))
    refund_ns = types.SimpleNamespace(create=lambda **kwargs: RefundObj())
    stripe_module = types.SimpleNamespace(checkout=checkout, Refund=refund_ns, api_key="")
    monkeypatch.setitem(sys.modules, "stripe", stripe_module)

    provider = StripeProvider({"secret_key": "sk_test_123", "webhook_secret": "whsec_123"})
    result = await provider.refund_payment("cs_test_123", amount=12.5)

    assert result["status"] == "refunded"
    assert result["refund_id"] == "re_test_123"
