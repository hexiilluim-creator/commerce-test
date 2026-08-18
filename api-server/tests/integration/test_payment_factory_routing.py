"""tests/integration/test_payment_factory_routing.py — Validation du routage pays → provider.

Couvre :
- TN → flouci/konnect/stripe/cash (ordre de priorité)
- MA → stripe/cash
- FR → stripe/cash
- DZ → stripe/cash
- AE → stripe/cash
- Pays inconnu → fallback stripe/cash
- Résolveur dynamique via payment_config
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Assure que la racine du projet est dans sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-32-characters-min")
os.environ.setdefault("ENCRYPTION_KEY", "HSs-6rKojKDyBDccY1QRXb-qF3hAfLJ6O9z_wpJdBMk=")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-characters-minimum")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token")

from services.payment_factory import (
    COUNTRY_DEFAULT_PROVIDER,
    _resolve_provider_name,
)


@pytest.mark.integration
@pytest.mark.payments
def test_tn_routing_all_four_providers():
    """Tunisie : les 4 providers doivent être présents dans l'ordre de priorité."""
    providers = COUNTRY_DEFAULT_PROVIDER.get("TN")
    assert providers is not None
    assert len(providers) == 4
    assert providers[0] == "flouci"
    assert providers[1] == "konnect"
    assert providers[2] == "stripe"
    assert providers[3] == "cash"


@pytest.mark.integration
@pytest.mark.payments
def test_ma_routing_stripe_cash():
    """Maroc : stripe puis cash."""
    providers = COUNTRY_DEFAULT_PROVIDER.get("MA")
    assert providers == ("stripe", "cash")


@pytest.mark.integration
@pytest.mark.payments
def test_fr_routing_stripe_cash():
    """France : stripe puis cash."""
    providers = COUNTRY_DEFAULT_PROVIDER.get("FR")
    assert providers == ("stripe", "cash")


@pytest.mark.integration
@pytest.mark.payments
def test_dz_routing_stripe_cash():
    """Algérie : stripe puis cash."""
    providers = COUNTRY_DEFAULT_PROVIDER.get("DZ")
    assert providers == ("stripe", "cash")


@pytest.mark.integration
@pytest.mark.payments
def test_ae_routing_stripe_cash():
    """Émirats Arabes Unis : stripe puis cash."""
    providers = COUNTRY_DEFAULT_PROVIDER.get("AE")
    assert providers == ("stripe", "cash")


@pytest.mark.integration
@pytest.mark.payments
def test_unknown_country_defaults_stripe_cash():
    """Un pays non répertorié doit fallback sur stripe/cash."""
    from services.payment_factory import _resolve_provider_name
    result = _resolve_provider_name("XX", None)
    assert result in ("stripe", "cash")


@pytest.mark.integration
@pytest.mark.payments
def test_resolve_provider_uses_config_over_default():
    """Si payment_config contient un provider valide, il doit être retourné."""
    config = {"flouci": True, "konnect": True}
    result = _resolve_provider_name("TN", config)
    assert result == "flouci"


@pytest.mark.integration
@pytest.mark.payments
def test_resolve_provider_none_country_fallback():
    """Si country est None et pas de config, fallback sur cash."""
    result = _resolve_provider_name(None, None)
    assert result == "cash"


@pytest.mark.integration
@pytest.mark.payments
def test_all_countries_have_at_least_two_providers():
    """Chaque pays doit avoir au moins 2 providers pour la redondance."""
    for country, providers in COUNTRY_DEFAULT_PROVIDER.items():
        assert len(providers) >= 2, f"{country} n'a que {len(providers)} provider(s)"


@pytest.mark.integration
@pytest.mark.payments
def test_cash_always_available():
    """Le provider 'cash' doit être disponible pour tous les pays."""
    for country, providers in COUNTRY_DEFAULT_PROVIDER.items():
        assert "cash" in providers, f"cash manquant pour {country}"
