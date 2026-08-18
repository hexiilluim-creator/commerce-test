import hashlib
import hmac
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.v1.social_webhooks import (
    _extract_meta_attachments,
    _validate_optional_signature,
    _validate_tiktok_signature,
    _dedupe_or_skip,
)


@pytest.mark.asyncio
async def test_social_webhook_signature_paths():
    body = b'{"id":1}'
    secret = "secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert await _validate_optional_signature("facebook", body, "", "") == "unsigned"
    assert await _validate_optional_signature("facebook", body, secret, "sha256=" + signature) == "validated"
    with pytest.raises(HTTPException) as missing:
        await _validate_optional_signature("facebook", body, secret, "")
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException):
        await _validate_tiktok_signature(body, secret, "bad")
    assert await _validate_tiktok_signature(body, "", "") == "unsigned"


def test_meta_attachment_normalization_filters_empty_items():
    result = _extract_meta_attachments({"attachments": [
        {"id": "a1", "type": "image", "payload": {"url": "https://cdn/a", "title": "A"}},
        {"id": None, "type": "file", "payload": {}},
    ]})
    assert result == [{"media_id": "a1", "url": "https://cdn/a", "mime_type": "image", "caption": "A"}]


@pytest.mark.asyncio
async def test_duplicate_social_webhook_is_recorded_and_skipped():
    payload = {"message_id": "m1", "sender_id": "s1", "recipient_id": "r1", "body": "hello"}
    with patch("api.v1.social_webhooks.claim_webhook_message", new=AsyncMock(return_value=False)), patch("api.v1.social_webhooks._record_social_event", new=AsyncMock()) as record:
        assert await _dedupe_or_skip(channel="facebook", store_id=4, payload=payload, signature_status="validated") is True
    record.assert_awaited_once()
