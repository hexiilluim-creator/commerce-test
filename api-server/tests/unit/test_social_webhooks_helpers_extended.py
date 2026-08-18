"""Tests complémentaires des garde-fous social webhooks."""
import hashlib
import hmac
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.v1 import social_webhooks as mod


@pytest.mark.asyncio
async def test_optional_signature_covers_unsigned_valid_missing_and_invalid():
    body = b'{"id":"x"}'
    assert await mod._validate_optional_signature("instagram", body, "", "") == "unsigned"
    digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert await mod._validate_optional_signature("instagram", body, "secret", "sha256=" + digest) == "validated"
    with pytest.raises(HTTPException) as missing:
        await mod._validate_optional_signature("instagram", body, "secret", "")
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException) as invalid:
        await mod._validate_optional_signature("instagram", body, "secret", "sha256=bad")
    assert invalid.value.status_code == 401


@pytest.mark.asyncio
async def test_tiktok_signature_uses_raw_digest_and_fail_closed():
    body = b"payload"
    digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert await mod._validate_tiktok_signature(body, "secret", digest) == "validated"
    assert await mod._validate_tiktok_signature(body, "", "") == "unsigned"
    with pytest.raises(HTTPException):
        await mod._validate_tiktok_signature(body, "secret", "bad")


def test_extract_meta_attachments_normalizes_and_filters_empty_items():
    result = mod._extract_meta_attachments({"attachments": [
        {"id": "a1", "type": "image", "payload": {"url": "https://img", "title": "car"}},
        {"id": "a2", "type": "audio", "payload": {"attachment_id": "media-2"}},
        {"id": "empty", "type": "text", "payload": {}},
    ]})
    assert result == [
        {"media_id": "a1", "url": "https://img", "mime_type": "image", "caption": "car"},
        {"media_id": "media-2", "url": None, "mime_type": "audio", "caption": None},
        {"media_id": "empty", "url": None, "mime_type": "text", "caption": None},
    ]


@pytest.mark.asyncio
async def test_dedupe_or_skip_records_replay(monkeypatch):
    monkeypatch.setattr(mod, "claim_webhook_message", AsyncMock(return_value=False))
    recorder = AsyncMock()
    monkeypatch.setattr(mod, "_record_social_event", recorder)
    payload = {"message_id": "m1", "sender_id": "s", "recipient_id": "r", "body": "x"}
    assert await mod._dedupe_or_skip(channel="instagram", store_id=4, payload=payload, signature_status="validated") is True
    recorder.assert_awaited_once()
    assert recorder.await_args.kwargs["status"] == "replayed"


@pytest.mark.asyncio
async def test_dedupe_or_skip_allows_first_delivery(monkeypatch):
    monkeypatch.setattr(mod, "claim_webhook_message", AsyncMock(return_value=True))
    monkeypatch.setattr(mod, "_record_social_event", AsyncMock())
    assert await mod._dedupe_or_skip(channel="facebook", store_id=None, payload={"message_id": "m2"}, signature_status="unsigned") is False



def test_attachment_and_observation_helpers_handle_empty_payload(monkeypatch):
    assert mod._extract_meta_attachments({}) == []
    from unittest.mock import MagicMock
    task = MagicMock()
    monkeypatch.setattr(mod.process_social_webhook, "delay", task)
    mod._enqueue_social_task({"message_id": "m"}, "facebook", 2, True)
    task.assert_called_once_with({"message_id": "m"}, "facebook", 2, True)
    observed = []
    monkeypatch.setattr(mod.webhook_processing_duration_seconds, "labels", lambda **kwargs: type("O", (), {"observe": lambda self, v: observed.append((kwargs, v))})())
    monkeypatch.setattr(mod.webhook_inflight, "labels", lambda **kwargs: type("O", (), {"dec": lambda self: observed.append((kwargs, "dec"))})())
    mod._observe_webhook_request("facebook", 0.0, "success")
    assert observed and observed[-1][1] == "dec"


from starlette.background import BackgroundTasks
from starlette.requests import Request


def _request(body: bytes, headers: dict[str, str] | None = None) -> Request:
    sent = False
    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}
    scope = {
        "type": "http", "method": "POST", "path": "/", "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ], "query_string": b"", "server": ("test", 80), "client": ("test", 1),
        "scheme": "http", "http_version": "1.1", "root_path": "",
    }
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_verify_social_channels_success_and_failures(monkeypatch):
    monkeypatch.setattr(mod.settings, "INSTAGRAM_VERIFY_TOKEN", "ig-token")
    monkeypatch.setattr(mod.settings, "FACEBOOK_VERIFY_TOKEN", "fb-token")
    monkeypatch.setattr(mod.settings, "TIKTOK_ENABLED", True)
    monkeypatch.setattr(mod.settings, "TIKTOK_VERIFY_TOKEN", "tt-token")
    assert (await mod.verify_instagram_webhook("subscribe", "123", "ig-token")).body == b"123"
    assert (await mod.verify_facebook_webhook("subscribe", "456", "fb-token")).body == b"456"
    assert (await mod.verify_tiktok_webhook("subscribe", "789", "tt-token")).body == b"789"
    assert await mod.verify_social_webhook_compat("subscribe", "42", "ig-token") == 42
    with pytest.raises(HTTPException):
        await mod.verify_instagram_webhook("x", "1", "bad")
    with pytest.raises(HTTPException):
        await mod.verify_social_webhook_compat("subscribe", "", "ig-token")
    monkeypatch.setattr(mod.settings, "TIKTOK_ENABLED", False)
    with pytest.raises(HTTPException) as disabled:
        await mod.verify_tiktok_webhook("subscribe", "1", "tt-token")
    assert disabled.value.status_code == 503


@pytest.mark.asyncio
async def test_receive_instagram_invalid_json_and_valid_message(monkeypatch):
    monkeypatch.setattr(mod.settings, "INSTAGRAM_APP_SECRET", "")
    monkeypatch.setattr(mod, "_record_invalid_json", AsyncMock())
    with pytest.raises(HTTPException) as invalid:
        await mod.receive_instagram_webhook(_request(b"{"), BackgroundTasks())
    assert invalid.value.status_code == 400
    monkeypatch.setattr(mod, "resolve_store_id_from_social_id", AsyncMock(return_value=7))
    monkeypatch.setattr(mod, "_record_social_event", AsyncMock())
    monkeypatch.setattr(mod, "claim_webhook_message", AsyncMock(return_value=True))
    monkeypatch.setattr(mod, "get_active_route_decision", lambda _: type("D", (), {"active": True, "reason": "test", "rollout_pct": 100, "bucket": 1})())
    monkeypatch.setattr(mod.process_social_webhook, "delay", lambda *args: None)
    body = b'{"entry":[{"messaging":[{"sender":{"id":"s"},"recipient":{"id":"r"},"message":{"mid":"m","text":"hello"}}]}]}'
    assert await mod.receive_instagram_webhook(_request(body), BackgroundTasks()) == {"status": "received"}


@pytest.mark.asyncio
async def test_receive_facebook_invalid_json_and_valid_message(monkeypatch):
    monkeypatch.setattr(mod.settings, "FACEBOOK_APP_SECRET", "")
    monkeypatch.setattr(mod, "_record_invalid_json", AsyncMock())
    with pytest.raises(HTTPException) as invalid:
        await mod.receive_facebook_webhook(_request(b"not-json"), BackgroundTasks())
    assert invalid.value.status_code == 400
    monkeypatch.setattr(mod, "resolve_store_id_from_social_id", AsyncMock(return_value=None))
    monkeypatch.setattr(mod, "_record_social_event", AsyncMock())
    monkeypatch.setattr(mod, "claim_webhook_message", AsyncMock(return_value=False))
    body = b'{"entry":[{"messaging":[{"sender":{"id":"s"},"recipient":{"id":"r"},"message":{"mid":"m"}}]}]}'
    assert await mod.receive_facebook_webhook(_request(body), BackgroundTasks()) == {"status": "received"}


@pytest.mark.asyncio
async def test_receive_tiktok_disabled_invalid_and_valid(monkeypatch):
    monkeypatch.setattr(mod.settings, "TIKTOK_ENABLED", False)
    assert await mod.receive_tiktok_webhook(_request(b"{}"), BackgroundTasks()) == {"status": "disabled"}
    monkeypatch.setattr(mod.settings, "TIKTOK_ENABLED", True)
    monkeypatch.setattr(mod.settings, "TIKTOK_APP_SECRET", "")
    monkeypatch.setattr(mod, "_record_invalid_json", AsyncMock())
    with pytest.raises(HTTPException) as invalid:
        await mod.receive_tiktok_webhook(_request(b"{"), BackgroundTasks())
    assert invalid.value.status_code == 400
    monkeypatch.setattr(mod, "resolve_store_id_from_social_id", AsyncMock(return_value=3))
    monkeypatch.setattr(mod, "_record_social_event", AsyncMock())
    monkeypatch.setattr(mod, "claim_webhook_message", AsyncMock(return_value=True))
    monkeypatch.setattr(mod, "get_active_route_decision", lambda _: type("D", (), {"active": False, "reason": "test", "rollout_pct": 0, "bucket": None})())
    body = b'{"open_id":"sender","business_account_id":"recipient","message_id":"mid","content":"hi"}'
    assert await mod.receive_tiktok_webhook(_request(body), BackgroundTasks()) == {"status": "received"}


@pytest.mark.asyncio
async def test_compat_receiver_handles_valid_and_invalid_json():
    assert await mod.receive_social_webhook_compat(_request(b"not-json")) == {"status": "received"}
    assert await mod.receive_social_webhook_compat(_request(b'{"entry":[]}')) == {"status": "received"}
