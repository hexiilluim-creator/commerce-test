from __future__ import annotations

import hashlib
import hmac
from unittest.mock import AsyncMock, patch

import pytest

from services import webhook_reliability as wr


@pytest.fixture(autouse=True)
def clear_memory_claims():
    wr._SEEN_MESSAGES.clear()
    yield
    wr._SEEN_MESSAGES.clear()


def test_claim_key_is_stable_and_hashes_body_without_message_id():
    direct = wr._build_claim_key("whatsapp", 4, "m1", "s", "r", "body")
    content = wr._build_claim_key("whatsapp", 4, None, "s", "r", "body")
    assert direct.endswith("whatsapp:4:m1")
    assert ":content:" in content
    assert content == wr._build_claim_key("whatsapp", 4, None, "s", "r", "body")


def test_signature_accepts_prefixed_and_raw_digest_but_rejects_invalid():
    payload = b'{"event":"created"}'
    secret = "webhook-secret"
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert wr.verify_signature(payload, secret, digest) is True
    assert wr.verify_signature(payload, secret, f"sha256={digest}") is True
    assert wr.verify_signature(payload, secret, "sha256=bad") is False
    assert wr.verify_signature(payload, "", digest) is False
    assert wr.verify_signature_from_headers({"x-hub-signature-256": digest}, payload, secret) is True


@pytest.mark.asyncio
async def test_memory_fallback_claims_first_delivery_and_rejects_duplicate():
    with patch("services.webhook_reliability._get_redis", new=AsyncMock(return_value=None)):
        assert await wr.claim_webhook_message(channel="whatsapp", store_id=1, message_id="m1") is True
        assert await wr.claim_webhook_message(channel="whatsapp", store_id=1, message_id="m1") is False
        stats = await wr.get_dedup_stats()
    assert stats["redis_available"] is False
    assert stats["memory_active_claims"] == 1


@pytest.mark.asyncio
async def test_redis_claim_uses_setnx_and_detects_duplicate():
    redis = AsyncMock()
    redis.set.side_effect = [True, False]
    redis.ping.return_value = True
    with patch("services.webhook_reliability._get_redis", new=AsyncMock(return_value=redis)):
        assert await wr.claim_webhook_message(channel="meta", store_id=2, message_id="m2") is True
        assert await wr.claim_webhook_message(channel="meta", store_id=2, message_id="m2") is False
    assert redis.set.await_count == 2
    assert redis.set.call_args.kwargs["nx"] is True
    assert redis.set.call_args.kwargs["ex"] == wr._DEDUP_TTL_SECONDS


@pytest.mark.asyncio
async def test_redis_error_falls_back_to_memory_and_release_removes_claim():
    redis = AsyncMock()
    redis.set.side_effect = RuntimeError("redis unavailable")
    redis.delete.return_value = 1
    with patch("services.webhook_reliability._get_redis", new=AsyncMock(return_value=redis)):
        assert await wr.claim_webhook_message(channel="sms", store_id=3, message_id="m3") is True
        await wr.release_webhook_claim("sms", 3, "m3")
        assert await wr.claim_webhook_message(channel="sms", store_id=3, message_id="m3") is True
    redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_memory_claim_is_reclaimable():
    key = wr._build_claim_key("email", 5, "m5", None, None, None)
    wr._SEEN_MESSAGES[key] = 0
    with patch("services.webhook_reliability._get_redis", new=AsyncMock(return_value=None)):
        assert await wr.claim_webhook_message(channel="email", store_id=5, message_id="m5") is True


@pytest.mark.asyncio
async def test_stats_reports_redis_count_when_available():
    redis = AsyncMock()
    redis.eval.return_value = 7
    with patch("services.webhook_reliability._get_redis", new=AsyncMock(return_value=redis)):
        stats = await wr.get_dedup_stats()
    assert stats["redis_available"] is True
    assert stats["redis_active_claims"] == 7
    assert stats["dedup_ttl_seconds"] == 172800
