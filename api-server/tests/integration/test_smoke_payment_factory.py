from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-32-characters-min")
os.environ.setdefault("ENCRYPTION_KEY", "HSs-6rKojKDyBDccY1QRXb-qF3hAfLJ6O9z_wpJdBMk=")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-characters-minimum")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token")

from services.payment_factory import COUNTRY_DEFAULT_PROVIDER


@pytest.mark.integration
@pytest.mark.payments
def test_smoke_payment_factory_country_routing():
    assert COUNTRY_DEFAULT_PROVIDER["TN"] == ("flouci", "konnect", "stripe", "cash")
    assert COUNTRY_DEFAULT_PROVIDER["MA"] == ("stripe", "cash")
    assert COUNTRY_DEFAULT_PROVIDER["FR"] == ("stripe", "cash")
    assert COUNTRY_DEFAULT_PROVIDER["DZ"] == ("stripe", "cash")
    assert COUNTRY_DEFAULT_PROVIDER["AE"] == ("stripe", "cash")
