from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.v1 import whatsapp as wa


def test_build_canonical_payload():
    msg = {"id": "m1", "from": "+216", "type": "text", "text": {"body": "hello"}}
    payload = wa._build_canonical_payload(msg=msg, store_id=4, phone_number_id="p1")
    assert payload["message_id"] == "m1"
    assert payload["id"] == "m1"
    assert payload["from_phone"] == "+216"
    assert payload["store_id"] == 4
    assert payload["raw_message"] == msg

@pytest.mark.asyncio
async def test_async_redis_pool_ping_and_failure():
    fake = AsyncMock()
    fake.ping = AsyncMock(return_value=True)
    with patch("redis.asyncio.from_url", return_value=fake) as factory, patch.object(wa, "_redis_pool", None):
        assert await wa._get_async_redis() is fake
        factory.assert_called_once()
    broken = AsyncMock()
    broken.ping.side_effect = RuntimeError("down")
    with patch.object(wa, "_redis_pool", broken):
        assert await wa._get_async_redis() is None
        assert wa._redis_pool is None

@pytest.mark.asyncio
async def test_duplicate_redis_first_duplicate_missing_and_error():
    assert await wa._is_duplicate_wa_message("", 1) is False
    redis = AsyncMock()
    redis.set = AsyncMock(side_effect=[True, False])
    with patch("api.v1.whatsapp._get_async_redis", new=AsyncMock(return_value=redis)):
        assert await wa._is_duplicate_wa_message("m", 1) is False
        assert await wa._is_duplicate_wa_message("m", 1) is True
    redis.set.side_effect = RuntimeError("redis down")
    with patch("api.v1.whatsapp._get_async_redis", new=AsyncMock(return_value=redis)):
        assert await wa._is_duplicate_wa_message("m2", 1) is False

@pytest.mark.asyncio
async def test_require_plan_tenant_and_feature_fail_closed():
    with patch("api.v1.whatsapp._sid", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await wa._require_whatsapp_plan()
        assert exc.value.status_code == 401
    snapshot = SimpleNamespace(plan_code="starter", has_feature=lambda feature: False)
    with patch("api.v1.whatsapp._sid", return_value=3), patch(
        "security_overlay.billing_overlay.get_billing_snapshot", new=AsyncMock(return_value=snapshot)
    ):
        with pytest.raises(HTTPException) as exc:
            await wa._require_whatsapp_plan()
        assert exc.value.status_code == 403
        assert exc.value.detail["required_plan"] == "pro_whatsapp"
    snapshot.has_feature = lambda feature: True
    with patch("api.v1.whatsapp._sid", return_value=3), patch(
        "security_overlay.billing_overlay.get_billing_snapshot", new=AsyncMock(return_value=snapshot)
    ):
        assert await wa._require_whatsapp_plan() is None

@pytest.mark.asyncio
async def test_verify_webhook_success_and_rejection():
    settings = SimpleNamespace(WHATSAPP_VERIFY_TOKEN="verify")
    with patch("api.v1.whatsapp.settings", settings):
        response = await wa.verify_webhook("subscribe", "raw-challenge", "verify")
        assert response.body == b"raw-challenge"
        with pytest.raises(HTTPException) as exc:
            await wa.verify_webhook("bad", "x", "verify")
        assert exc.value.status_code == 403

@pytest.mark.asyncio
async def test_resolve_store_id_mapping():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = SimpleNamespace(store_id=9)
    db.execute.return_value = result
    assert await wa._resolve_store_id(db, None) is None
    assert await wa._resolve_store_id(db, "phone") == 9
    db.execute.return_value.scalar_one_or_none.return_value = None
    assert await wa._resolve_store_id(db, "unknown") is None

@pytest.mark.asyncio
async def test_push_stream_is_fail_safe_and_maps_payload():
    payload = {"id": "m", "from": "+1", "body": "hello", "type": "text"}
    with patch("api.v1.whatsapp._mq.push_message", new=AsyncMock()) as push, patch(
        "api.v1.whatsapp._metrics.redis_operations_total"
    ) as metric:
        await wa._push_to_stream(payload, 7)
        push.assert_awaited_once_with({"message_id": "m", "store_id": "7", "from_phone": "+1", "body": "hello", "type": "text"})
        metric.labels.return_value.inc.assert_called_once()
    with patch("api.v1.whatsapp._mq.push_message", new=AsyncMock(side_effect=RuntimeError("down"))), patch(
        "api.v1.whatsapp._metrics.redis_operations_total"
    ) as metric:
        await wa._push_to_stream(payload, None)
        metric.labels.return_value.inc.assert_called_once()

@pytest.mark.asyncio
async def test_fallback_and_shadow_are_non_throwing():
    task = MagicMock()
    task.delay = MagicMock(side_effect=RuntimeError("celery down"))
    with patch("api.v1.whatsapp.process_whatsapp_message", task):
        wa._v8_fallback({"from": "+1", "text": "hi"}, 5)
        assert task.delay.called
    with patch("omnicall_v9.shadow_mode.run_shadow_v9", side_effect=RuntimeError("shadow")):
        wa._shadow_v9_task({"id": "m"}, "whatsapp", 5)
