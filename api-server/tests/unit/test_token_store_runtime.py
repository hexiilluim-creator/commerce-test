import time
from unittest.mock import AsyncMock, patch

import pytest

from services import token_store


@pytest.mark.asyncio
async def test_token_store_memory_fallback_lifecycle():
    token_store._mem_store.clear()
    redis = AsyncMock()
    redis.setex.side_effect = RuntimeError("redis down")
    redis.get.side_effect = RuntimeError("redis down")
    redis.delete.side_effect = RuntimeError("redis down")
    with patch("services.redis_lock.get_redis", return_value=redis), patch.dict("os.environ", {"ENV": "test"}, clear=False):
        await token_store.set_token("abc", {"user": 1}, ttl_seconds=60)
        assert await token_store.get_token("abc") == {"user": 1}
        await token_store.delete_token("abc")
        assert await token_store.get_token("abc") is None


@pytest.mark.asyncio
async def test_token_store_expiration_and_production_no_fallback():
    token_store._mem_store.clear()
    with patch("services.redis_lock.get_redis", side_effect=RuntimeError("redis down")), patch("services.token_store._allow_memory_fallback", return_value=False), patch.dict("os.environ", {"ENV": "production"}, clear=False):
        await token_store.set_token("prod", "secret", ttl_seconds=1)
        assert await token_store.get_token("prod") is None
    token_store._mem_store["expired"] = ("x", time.time() - 1)
    assert await token_store.get_token("expired") is None


@pytest.mark.asyncio
async def test_token_store_redis_json_roundtrip():
    redis = AsyncMock()
    redis.get.return_value = '{"ok": true}'
    with patch("services.redis_lock.get_redis", return_value=redis):
        await token_store.set_token("redis", {"ok": True}, ttl_seconds=10)
        assert await token_store.get_token("redis") == {"ok": True}
        await token_store.delete_token("redis")
    redis.setex.assert_awaited_once()
    redis.delete.assert_awaited_once_with("tok:redis")
