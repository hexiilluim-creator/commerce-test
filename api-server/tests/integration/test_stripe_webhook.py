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
def test_stripe_webhook_construct_event_is_called(monkeypatch):
    called = {}

    def construct_event(payload, signature, secret):
        called["payload"] = payload
        called["signature"] = signature
        called["secret"] = secret
        return {"id": "evt_test"}

    stripe_module = types.SimpleNamespace(Webhook=types.SimpleNamespace(construct_event=construct_event))
    monkeypatch.setitem(sys.modules, "stripe", stripe_module)

    provider = StripeProvider({"secret_key": "sk_test_123", "webhook_secret": "whsec_123"})
    payload = b'{"id":"evt_test"}'
    ok, status = provider.verify_webhook_signature(payload, {"stripe-signature": "t=1,v1=fake"})

    assert ok is True
    assert status == "verified"
    assert called["secret"] == "whsec_123"
