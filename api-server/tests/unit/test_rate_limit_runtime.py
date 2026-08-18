from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from middleware import rate_limit


def test_resolve_store_id_precedence_and_invalid_values():
    req = SimpleNamespace(state=SimpleNamespace(store_id=7), headers={})
    assert rate_limit._resolve_store_id(req) == 7
    req = SimpleNamespace(state=SimpleNamespace(store_id=None), headers={"X-Store-Id": "8"})
    assert rate_limit._resolve_store_id(req) == 8
    req = SimpleNamespace(state=SimpleNamespace(store_id=None), headers={"X-Store-Id": "bad"})
    assert rate_limit._resolve_store_id(req) is None


@pytest.mark.asyncio
async def test_check_tenant_bucket_sets_expiry_and_returns_status():
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=(2, -1))
    redis = MagicMock(pipeline=MagicMock(return_value=pipe), expire=AsyncMock())
    allowed, ttl = await rate_limit._check_tenant_bucket(redis, key="k", limit=2, window_seconds=60)
    assert allowed is True and ttl == 60
    redis.expire.assert_awaited_once_with("k", 60)


@pytest.mark.asyncio
async def test_enforce_tenant_rate_limit_raises_429_when_bucket_exceeded():
    request = SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"), state=SimpleNamespace(store_id=9), headers={})
    with patch.object(rate_limit, "_is_test", False), patch.object(rate_limit, "_get_tenant_rl_redis", new=AsyncMock(return_value=MagicMock())), patch.object(rate_limit, "_check_tenant_bucket", new=AsyncMock(side_effect=[(False, 10), (True, 10)])):
        with pytest.raises(HTTPException) as exc:
            await rate_limit._enforce_tenant_rate_limit(request, limit=1, window_seconds=60, scope="ai")
    assert exc.value.status_code == 429
