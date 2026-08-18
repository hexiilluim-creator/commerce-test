from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.v1.payments import (
    PaymentIntentRequest,
    _compute_hmac,
    _decrypt_cfg,
    _extract_bearer_token,
    compute_paymee_checksum,
)


def test_payment_intent_schema_and_bearer_extraction():
    assert PaymentIntentRequest(order_id=1, provider="paymee").provider == "paymee"
    with pytest.raises(ValidationError):
        PaymentIntentRequest(order_id=1, provider="stripe")
    assert _extract_bearer_token(SimpleNamespace(headers={"Authorization": "Bearer abc123"})) == "abc123"
    assert _extract_bearer_token(SimpleNamespace(headers={"Authorization": "raw-token"})) == "raw-token"
    assert _extract_bearer_token(SimpleNamespace(headers={})) == ""


def test_payment_crypto_helpers_are_deterministic():
    assert _compute_hmac("secret", b"payload") == _compute_hmac("secret", b"payload")
    assert _compute_hmac("secret", b"payload") != _compute_hmac("other", b"payload")
    assert compute_paymee_checksum("api", 12.5, "tok") == "d484d9d3b7751363293413824a4c4fdd3abed43fa85883ed622b83ef8efc8e0b"


def test_decrypt_cfg_success_and_failure():
    with patch("api.v1.payments.settings", SimpleNamespace(decrypt=lambda value: f"plain-{value}")):
        assert _decrypt_cfg({"api_key": "enc_secret", "enabled": True}) == {"api_key": "plain-secret", "enabled": True}
    with patch("api.v1.payments.settings", SimpleNamespace(decrypt=MagicMock(side_effect=RuntimeError("bad key")))):
        with pytest.raises(HTTPException) as exc:
            _decrypt_cfg({"api_key": "enc_secret"})
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_load_store_payment_config_missing_store_or_provider():
    from api.v1.payments import _load_store_payment_cfg
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    with pytest.raises(HTTPException) as exc:
        await _load_store_payment_cfg(db, 1, "paymee")
    assert exc.value.status_code == 400

    result.scalar_one_or_none.return_value = SimpleNamespace(payment_config={"cash": {}})
    with pytest.raises(HTTPException) as exc:
        await _load_store_payment_cfg(db, 1, "paymee")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_payment_webhook_validators_accept_valid_credentials():
    from api.v1.payments import _validate_flouci, _validate_clix, _validate_tnpay
    order = SimpleNamespace(store_id=7)
    db = AsyncMock()
    with patch("api.v1.payments._load_order_and_cfg", new=AsyncMock(return_value=(order, {"secret_key": "s", "webhook_token": "tok"}))):
        req = SimpleNamespace(headers={"X-Flouci-Signature": _compute_hmac("s", b"body")})
        assert await _validate_flouci(db, b"body", req, {}, "e", "1") == 7
        req = SimpleNamespace(headers={"X-Clix-Token": "tok"})
        assert await _validate_clix(db, req, {}, "e", "1") == 7
        req = SimpleNamespace(headers={"X-TnPay-Token": "tok"})
        assert await _validate_tnpay(db, req, {}, "e", "1") == 7
