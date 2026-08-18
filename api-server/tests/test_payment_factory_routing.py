from __future__ import annotations

from services.payment_factory import COUNTRY_DEFAULT_PROVIDER


def test_smoke_payment_factory_routing():
    assert COUNTRY_DEFAULT_PROVIDER["TN"] == ("flouci", "konnect", "stripe", "cash")
