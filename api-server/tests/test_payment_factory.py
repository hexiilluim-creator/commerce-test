"""tests/test_payment_factory.py — Couverture de services/payment_factory.py.

4 tests obligatoires (cahier des charges) :
  1. create_payment_link Flouci -> URL retournée
  2. verify_payment Flouci -> status=paid
  3. CashProvider sans config -> instruction livraison
  4. déchiffrement de config corrompue -> HTTPException 503

Stratégie : on monkey-patche `httpx.AsyncClient.request` via un mock asynchrone,
ce qui évite tout appel réseau réel — tests rapides et déterministes.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

# Assure que la racine du projet est dans sys.path quand pytest est lancé depuis
# n'importe quel CWD (cohérent avec tests/test_imports.py).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ──────────────────────────────────────────────────────────────────────────────
# Variables d'environnement minimales pour permettre l'import de config.Settings
# AVANT toute importation du module payment_factory (qui charge `config`).
# ──────────────────────────────────────────────────────────────────────────────
import os  # noqa: E402

os.environ.setdefault("ENV", "development")
os.environ.setdefault("DEBUG", "True")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost/test",
)
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test_jwt_secret_for_unit_tests_only_0000000000000000",
)
# Fernet key valide (32 bytes base64) — utilisée uniquement par les tests
os.environ.setdefault("ENCRYPTION_KEY", "HSs-6rKojKDyBDccY1QRXb-qF3hAfLJ6O9z_wpJdBMk=")
os.environ.setdefault(
    "CSRF_SECRET",
    "test_csrf_secret_for_unit_tests_only_000000000000000",
)
# Évite que la validation Pydantic rejette le verify token par défaut
os.environ.setdefault("WHATSAPP_APP_SECRET", "")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test_health_token_unit")

from services.payment_factory import (  # noqa: E402
    CashProvider,
    FlouciProvider,
    PaymentFactory,
    _decrypt_config,
)


class _MockResponse:
    """Mock minimaliste d'une httpx.Response — couvre .json() et .status_code."""

    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 — Flouci create_payment_link -> URL
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
async def test_flouci_create_payment_link_returns_url():
    provider = FlouciProvider(cfg={"app_token": "tok_test", "app_secret": "sec_test"})

    fake_response = _MockResponse(
        200,
        {
            "result": {
                "link": "https://flouci.app/checkout/abc123",
                "payment_id": "pay_xyz789",
            }
        },
    )

    with patch(
        "services.payment_factory._http_request_with_retry",
        new=AsyncMock(return_value=fake_response),
    ) as mock_request:
        result = await provider.create_payment_link(
            amount=42.5,
            currency="TND",
            description="Test order",
            reference="order-1",
        )

    assert result["url"] == "https://flouci.app/checkout/abc123"
    assert result["id"] == "pay_xyz789"
    assert result["provider"] == "flouci"
    # Vérifie qu'on a bien appelé POST sur l'URL Flouci
    mock_request.assert_awaited_once()
    call_kwargs = mock_request.await_args.kwargs
    call_args = mock_request.await_args.args
    assert call_args[0] == "POST"
    assert "developers.flouci.app" in call_args[1]
    # Montant converti en millimes : 42.5 TND -> 42500
    assert call_kwargs["json_payload"]["amount"] == "42500"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 — Flouci verify_payment -> status=paid
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
async def test_flouci_verify_payment_paid():
    provider = FlouciProvider(cfg={"app_token": "tok_test", "app_secret": "sec_test"})

    fake_response = _MockResponse(
        200,
        {"result": {"status": "SUCCESS", "payment_id": "pay_xyz789"}},
    )

    with patch(
        "services.payment_factory._http_request_with_retry",
        new=AsyncMock(return_value=fake_response),
    ):
        result = await provider.verify_payment("pay_xyz789")

    assert result["status"] == "paid"
    assert result["provider"] == "flouci"
    assert result["raw"] == "SUCCESS"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 — CashProvider sans config -> instruction livraison
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
async def test_cash_provider_without_config_returns_delivery_instruction():
    provider = CashProvider()  # aucune config requise
    result = await provider.create_payment_link(
        amount=100.0,
        currency="TND",
        description="Achat boutique",
        reference="cash-1",
    )

    assert result["url"] is None
    assert result["method"] == "cash"
    assert result["instruction"] == "Paiement à la livraison"

    # verify_payment doit retourner pending_cash (le livreur confirme manuellement)
    verify = await provider.verify_payment("cash-1")
    assert verify["status"] == "pending_cash"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 — Déchiffrement de config corrompue -> HTTPException 503
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_decrypt_corrupted_config_raises_503():
    # Valeur préfixée 'enc_' mais qui n'est PAS un ciphertext Fernet valide
    raw_cfg = {
        "app_token": "enc_corrupted_base64_not_a_valid_fernet_token",
        "wallet_id": "plain_value_kept_as_is",
    }

    with pytest.raises(HTTPException) as excinfo:
        _decrypt_config(raw_cfg)

    assert excinfo.value.status_code == 503
    # Le message ne doit JAMAIS contenir la valeur corrompue
    assert "corrupted_base64" not in str(excinfo.value.detail)


# ══════════════════════════════════════════════════════════════════════════════
# Bonus : factory routing
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_factory_get_unknown_provider_raises_400():
    with pytest.raises(HTTPException) as excinfo:
        PaymentFactory.get("provider_inexistant")
    assert excinfo.value.status_code == 400


@pytest.mark.unit
def test_factory_get_cash_without_cfg_ok():
    adapter = PaymentFactory.get("cash")
    assert isinstance(adapter, CashProvider)
