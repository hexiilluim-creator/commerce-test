from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-32-characters-min")
os.environ.setdefault("ENCRYPTION_KEY", "HSs-6rKojKDyBDccY1QRXb-qF3hAfLJ6O9z_wpJdBMk=")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-characters-minimum")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token")

from api.v1.payments import compute_paymee_checksum
from services.payment_factory import PaymeeProvider


@pytest.mark.integration
@pytest.mark.payments
def test_paymee_checksum_matches_sha256_api_key_amount_token():
    api_key = "paymee-secret"
    token = "pm-test-1"
    amount = 100.5
    checksum = compute_paymee_checksum(api_key, amount, token)

    provider = PaymeeProvider({"api_key": api_key, "vendor_id": "1234"})
    payload = (
        f'{{"token":"{token}","amount":{amount:.3f},"check_sum":"{checksum}"}}'
    ).encode()

    ok, status = provider.verify_webhook_signature(payload, {})
    assert ok is True
    assert status == "verified"
