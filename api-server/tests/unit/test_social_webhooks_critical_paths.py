from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.v1 import social_webhooks as sw


def request(body: bytes = b"{}", headers: dict[str, str] | None = None) -> Request:
    headers = headers or {}
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    scope = {"type": "http", "method": "POST", "path": "/", "headers": raw_headers, "query_string": b""}
    r = Request(scope, receive)
    return r


@pytest.mark.asyncio
async def test_optional_signature_unsigned_valid_and_invalid():
    body = b'{"x":1}'
    assert await sw._validate_optional_signature("facebook", body, "", "") == "unsigned"
    digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert await sw._validate_optional_signature("facebook", body, "secret", "sha256=" + digest) == "validated"
    with pytest.raises(HTTPException, match="Missing Facebook"):
        await sw._validate_optional_signature("facebook", body, "secret", "")
    with pytest.raises(HTTPException, match="Invalid Facebook"):
        await sw._validate_optional_signature("facebook", body, "secret", "bad")

@pytest.mark.asyncio
async def test_tiktok_signature_paths():
    body = b"payload"
    assert await sw._validate_tiktok_signature(body, "", "") == "unsigned"
    digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert await sw._validate_tiktok_signature(body, "secret", digest) == "validated"
    with pytest.raises(HTTPException, match="Missing TikTok"):
        await sw._validate_tiktok_signature(body, "secret", "")
    with pytest.raises(HTTPException, match="Invalid TikTok"):
        await sw._validate_tiktok_signature(body, "secret", "bad")


def test_extract_meta_attachments_filters_empty_and_normalizes():
    result = sw._extract_meta_attachments({"attachments": [
        {"id": "a", "type": "image", "payload": {"url": "u", "title": "T"}},
        {"id": "b", "mime_type": "video/mp4", "payload": {"attachment_id": "media-b"}},
        {"id": "empty", "payload": {}},
    ]})
    assert result == [
        {"media_id": "a", "url": "u", "mime_type": "image", "caption": "T"},
        {"media_id": "media-b", "url": None, "mime_type": "video/mp4", "caption": None},
        {"media_id": "empty", "url": None, "mime_type": None, "caption": None},
    ]
    assert sw._extract_meta_attachments({}) == []

@pytest.mark.asyncio
async def test_dedupe_first_and_duplicate_paths():
    payload = {"message_id": "m", "sender_id": "s", "recipient_id": "r", "body": "hi"}
    with patch("api.v1.social_webhooks.claim_webhook_message", new=AsyncMock(return_value=True)):
        assert await sw._dedupe_or_skip(channel="facebook", store_id=1, payload=payload, signature_status="validated") is False
    with patch("api.v1.social_webhooks.claim_webhook_message", new=AsyncMock(return_value=False)), patch(
        "api.v1.social_webhooks._record_social_event", new=AsyncMock()
    ) as record:
        assert await sw._dedupe_or_skip(channel="facebook", store_id=1, payload=payload, signature_status="validated") is True
        record.assert_awaited_once()

@pytest.mark.asyncio
async def test_record_helpers_persist_and_reject():
    db = MagicMock()
    db.commit = AsyncMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=None)
    with patch("api.v1.social_webhooks.AsyncSessionLocal", return_value=session), patch(
        "api.v1.social_webhooks.record_workflow_event", new=AsyncMock()
    ) as record:
        await sw._record_social_event(channel="instagram", status="received", store_id=2, payload={"message_id": "m"}, signature_status="unsigned")
        record.assert_awaited_once()
        assert db.commit.await_count == 1
    with patch("api.v1.social_webhooks._record_social_event", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await sw._reject_social_webhook(channel="instagram", store_id=None, payload={}, signature_status="rejected", detail="bad")
        assert exc.value.status_code == 401

@pytest.mark.asyncio
async def test_invalid_json_record_helper_truncates_raw_body():
    with patch("api.v1.social_webhooks._record_social_event", new=AsyncMock()) as record:
        await sw._record_invalid_json("facebook", b"x" * 1500)
    payload = record.await_args.kwargs["payload"]
    assert len(payload["raw"]) == 1000
    assert record.await_args.kwargs["signature_status"] == "invalid_json"

@pytest.mark.asyncio
async def test_verify_endpoints_success_and_failure():
    settings = SimpleNamespace(INSTAGRAM_VERIFY_TOKEN="ig", FACEBOOK_VERIFY_TOKEN="fb", TIKTOK_VERIFY_TOKEN="tt", TIKTOK_ENABLED=True)
    with patch("api.v1.social_webhooks.settings", settings):
        assert (await sw.verify_instagram_webhook("subscribe", "challenge", "ig")).body == b"challenge"
        assert (await sw.verify_facebook_webhook("subscribe", "challenge", "fb")).body == b"challenge"
        assert (await sw.verify_tiktok_webhook("subscribe", "challenge", "tt")).body == b"challenge"
        with pytest.raises(HTTPException) as exc:
            await sw.verify_instagram_webhook("bad", "x", "ig")
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException) as exc:
            await sw.verify_facebook_webhook("bad", "x", "fb")
        assert exc.value.status_code == 403
    with patch("api.v1.social_webhooks.settings", SimpleNamespace(TIKTOK_ENABLED=False)):
        with pytest.raises(HTTPException) as exc:
            await sw.verify_tiktok_webhook("subscribe", "x", "tt")
        assert exc.value.status_code == 503


def test_enqueue_and_observe_helpers():
    task = MagicMock()
    task.delay = MagicMock()
    with patch("api.v1.social_webhooks.process_social_webhook", task):
        sw._enqueue_social_task({"x": 1}, "facebook", 1, True)
    task.delay.assert_called_once_with({"x": 1}, "facebook", 1, True)
    with patch("api.v1.social_webhooks.webhook_processing_duration_seconds") as duration, patch(
        "api.v1.social_webhooks.webhook_inflight"
    ) as inflight:
        sw._observe_webhook_request("facebook", 0.0, "success")
    duration.labels.return_value.observe.assert_called_once()
    inflight.labels.return_value.dec.assert_called_once()
