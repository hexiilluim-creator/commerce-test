from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.v1.payments import (
    _compute_hmac,
    _decrypt_cfg,
    _extract_bearer_token,
    _load_order_and_cfg,
    compute_paymee_checksum,
)


def _request(headers):
    scope = {"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    return Request(scope)


def test_payments_helpers_bearer_hmac_checksum_and_decrypt():
    assert _extract_bearer_token(_request({"Authorization": "Bearer abc"})) == "abc"
    assert _extract_bearer_token(_request({"Authorization": "raw"})) == "raw"
    assert _compute_hmac("s", b"body")
    assert compute_paymee_checksum("key", 12.5, "tok") == compute_paymee_checksum("key", 12.5, "tok")
    with patch("api.v1.payments.settings", SimpleNamespace(decrypt=lambda value: "secret")):
        assert _decrypt_cfg({"api_key": "enc_cipher", "sandbox": True}) == {"api_key": "secret", "sandbox": True}


@pytest.mark.asyncio
async def test_load_order_and_payment_config_rejects_invalid_or_missing_data():
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: None)
    with pytest.raises(HTTPException) as invalid:
        await _load_order_and_cfg(db, "cash", "bad")
    assert invalid.value.status_code == 400
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(id=4, store_id=2))
    with patch("api.v1.payments._load_store_payment_cfg", new=AsyncMock(side_effect=HTTPException(status_code=400, detail="missing"))):
        with pytest.raises(HTTPException) as missing:
            await _load_order_and_cfg(db, "cash", "4")
    assert missing.value.status_code == 400
