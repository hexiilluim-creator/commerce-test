from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import redis_lock


@pytest.mark.asyncio
async def test_noop_lock_service_context_try_and_release():
    service = redis_lock._NoOpLockService()
    async with service.acquire("k", timeout=1) as acquired:
        assert acquired is True
    assert await service.try_acquire("k") is True
    assert await service.release("k") is None


@pytest.mark.asyncio
async def test_redis_lock_context_acquired_deletes_key():
    client = AsyncMock()
    client.set.return_value = True
    service = redis_lock._RedisLockService()
    with patch("services.redis_lock.get_redis", return_value=client):
        async with service.acquire("slot", timeout=9) as acquired:
            assert acquired is True
    client.set.assert_awaited_once_with("omnicall:lock:slot", "1", nx=True, ex=9)
    client.delete.assert_awaited_once_with("omnicall:lock:slot")


@pytest.mark.asyncio
async def test_redis_lock_context_not_acquired_keeps_key():
    client = AsyncMock()
    client.set.return_value = None
    with patch("services.redis_lock.get_redis", return_value=client):
        async with redis_lock._RedisLockService().acquire("slot") as acquired:
            assert acquired is False
    client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_lock_try_and_release():
    client = AsyncMock()
    client.set.return_value = 1
    with patch("services.redis_lock.get_redis", return_value=client):
        service = redis_lock._RedisLockService()
        assert await service.try_acquire("a", timeout=4) is True
        await service.release("a")
    assert client.delete.await_args.args == ("omnicall:lock:a",)


@pytest.mark.asyncio
async def test_lock_facades_return_token_and_release_only_when_present():
    fake = MagicMock()
    fake.try_acquire = AsyncMock(side_effect=[True, False])
    fake.release = AsyncMock()
    with patch.object(redis_lock, "lock_service", fake):
        assert await redis_lock.acquire_lock("a", ttl=3) == "1"
        assert await redis_lock.acquire_lock("b", ttl=3) is None
        await redis_lock.release_lock("a", "1")
        await redis_lock.release_lock("b", None)
    fake.release.assert_awaited_once_with("a")
