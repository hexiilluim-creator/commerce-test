from __future__ import annotations

import hashlib
import hmac
import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-32-characters-min")
os.environ.setdefault("ENCRYPTION_KEY", "HSs-6rKojKDyBDccY1QRXb-qF3hAfLJ6O9z_wpJdBMk=")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-characters-minimum")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token")

from services.payment_factory import KonnectProvider


@pytest.mark.integration
@pytest.mark.payments
def test_konnect_signature_validates_hmac_sha256():
    payload = b'{"paymentRef":"kn-test-1","status":"completed"}'
    secret = "konnect-secret"
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    provider = KonnectProvider({"api_key": secret, "receiver_wallet_id": "wallet-1", "webhook_secret": secret})
    ok, status = provider.verify_webhook_signature(payload, {"x-signature": signature})

    assert ok is True
    assert status == "verified"
