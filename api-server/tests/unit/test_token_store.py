from __future__ import annotations

import pytest

import services.redis_lock as redis_lock
from services import token_store


@pytest.fixture(autouse=True)
def clear_mem_store() -> None:
    token_store._mem_store.clear()
    yield
    token_store._mem_store.clear()


def _raise_redis_unavailable():
    raise RuntimeError("redis unavailable")


@pytest.mark.asyncio
async def test_token_store_memory_fallback_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_lock, "get_redis", _raise_redis_unavailable)

    await token_store.set_token("reset-1", {"user_id": 12}, ttl_seconds=60)

    assert await token_store.get_token("reset-1") == {"user_id": 12}

    await token_store.delete_token("reset-1")

    assert await token_store.get_token("reset-1") is None


@pytest.mark.asyncio
async def test_token_store_memory_fallback_expires_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_lock, "get_redis", _raise_redis_unavailable)

    fake_now = [1000.0]
    monkeypatch.setattr(token_store.time, "time", lambda: fake_now[0])

    await token_store.set_token("reset-2", "payload", ttl_seconds=10)
    assert await token_store.get_token("reset-2") == "payload"

    fake_now[0] = 1011.0

    assert await token_store.get_token("reset-2") is None
    assert "reset-2" not in token_store._mem_store
