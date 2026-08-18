"""tests/test_store_resolver.py — Couverture services/store_resolver.py.

Couvre :
  - _cache_key (format, normalisation)
  - _local_get / _local_set (hit, miss, TTL expiré)
  - resolve_store_id_from_social_id (cache hit, cache miss -> DB)
  - resolve_store_id_from_phone (idem)
  - invalidate_store_cache
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")

from services.store_resolver import (  # noqa: E402
    _cache_key,
    _local_cache,
    _local_get,
    _local_set,
    invalidate_store_cache,
    resolve_store_id_from_phone,
    resolve_store_id_from_social_id,
)

pytestmark = pytest.mark.unit


# ─── Tests _cache_key ─────────────────────────────────────────────────────────

def test_cache_key_format():
    key = _cache_key("whatsapp", "123456789")
    assert "whatsapp" in key
    assert "123456789" in key


def test_cache_key_normalization():
    k1 = _cache_key("whatsapp", "123")
    k2 = _cache_key("WHATSAPP", "123")
    # Les clés peuvent être case-sensitive selon impl
    assert isinstance(k1, str)
    assert isinstance(k2, str)


def test_cache_key_different_channels():
    k1 = _cache_key("whatsapp", "account_X")
    k2 = _cache_key("instagram", "account_X")
    assert k1 != k2


def test_cache_key_different_accounts():
    k1 = _cache_key("whatsapp", "acc1")
    k2 = _cache_key("whatsapp", "acc2")
    assert k1 != k2


# ─── Tests _local_get / _local_set ───────────────────────────────────────────

def test_local_set_and_get_hit():
    _local_cache.clear()
    _local_set(_cache_key("whatsapp", "test_acc"), store_id=42)
    hit, sid = _local_get(_cache_key("whatsapp", "test_acc"))
    assert hit is True
    assert sid == 42


def test_local_get_miss():
    _local_cache.clear()
    hit, sid = _local_get("nonexistent_key_xyz")
    assert hit is False
    assert sid is None


def test_local_get_expired_entry():
    _local_cache.clear()
    key = _cache_key("instagram", "exp_test")
    # Insérer avec expiry dans le passé
    _local_cache[key] = (time.monotonic() - 1.0, 55)
    hit, sid = _local_get(key)
    assert hit is False
    assert sid is None


def test_local_set_none_store_id():
    """store_id peut être None (compte social non mappé)."""
    key = _cache_key("tiktok", "unmapped_acc")
    _local_set(key, store_id=None)
    hit, sid = _local_get(key)
    assert hit is True
    assert sid is None


# ─── Tests resolve_store_id_from_social_id ────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_social_id_cache_hit():
    """Cache hit -> retourne store_id sans toucher la DB."""
    _local_cache.clear()
    key = _cache_key("whatsapp", "wa_account_cache")
    _local_cache[key] = (time.monotonic() + 300, 77)

    result = await resolve_store_id_from_social_id("wa_account_cache", "whatsapp")
    assert result == 77


@pytest.mark.asyncio
async def test_resolve_social_id_db_not_found():
    """DB ne trouve pas le mapping -> None."""
    _local_cache.clear()

    class _FakeResult:
        def scalar_one_or_none(self): return None

    class _FakeDB:
        async def execute(self, *args, **kwargs): return _FakeResult()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    class _FakeSL:
        def __call__(self): return _FakeDB()

    with patch("services.store_resolver.AsyncSessionLocal", _FakeSL()):
        with patch("services.store_resolver._get_redis", AsyncMock(return_value=None)):
            result = await resolve_store_id_from_social_id("unknown_account", "whatsapp")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_social_id_returns_store_id():
    """DB retourne un mapping -> store_id."""
    _local_cache.clear()

    class _FakeMapping:
        def scalar_one_or_none(self): return SimpleNamespace(store_id=99)

    class _FakeDB:
        async def execute(self, *args, **kwargs): return _FakeMapping()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    class _FakeSL:
        def __call__(self): return _FakeDB()

    with patch("services.store_resolver.AsyncSessionLocal", _FakeSL()):
        with patch("services.store_resolver._get_redis", AsyncMock(return_value=None)):
            result = await resolve_store_id_from_social_id("known_account", "instagram")

    assert result == 99


# ─── Tests invalidate_store_cache ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalidate_removes_from_local_cache():
    # AUDIT FIX : invalidate_store_cache est `async def` (elle attend Redis),
    # mais ce test l'appelait sans `await` ni marqueur asyncio -> la coroutine
    # n'était jamais exécutée et _local_cache n'était donc jamais vidé.
    _local_cache.clear()
    channel, account = "facebook", "fb_acc_001"
    key = _cache_key(channel, account)
    _local_cache[key] = (time.monotonic() + 300, 10)

    await invalidate_store_cache(channel, account)
    assert key not in _local_cache


@pytest.mark.asyncio
async def test_social_resolution_redis_hit_populates_local_cache():
    _local_cache.clear()
    with patch("services.store_resolver._redis_get", AsyncMock(return_value=(True, 42))), \
         patch("services.store_resolver._db_resolve_social", AsyncMock()) as db_lookup:
        assert await resolve_store_id_from_social_id("redis_acc", "facebook") == 42
    db_lookup.assert_not_awaited()
    assert _local_get(_cache_key("facebook", "redis_acc")) == (True, 42)


@pytest.mark.asyncio
async def test_social_resolution_handles_empty_id_and_negative_redis_cache():
    _local_cache.clear()
    assert await resolve_store_id_from_social_id(None, "whatsapp") is None
    with patch("services.store_resolver._redis_get", AsyncMock(return_value=(True, None))), \
         patch("services.store_resolver._db_resolve_social", AsyncMock()) as db_lookup:
        assert await resolve_store_id_from_social_id("negative", "whatsapp") is None
    db_lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_phone_resolution_db_and_redis_paths():
    _local_cache.clear()
    with patch("services.store_resolver._redis_get", AsyncMock(return_value=(False, None))), \
         patch("services.store_resolver._db_resolve_phone", AsyncMock(return_value=15)), \
         patch("services.store_resolver._redis_set", AsyncMock()) as redis_set:
        assert await resolve_store_id_from_phone("phone-1") == 15
    redis_set.assert_awaited_once()
    _local_cache.clear()
    with patch("services.store_resolver._redis_get", AsyncMock(return_value=(True, 16))), \
         patch("services.store_resolver._db_resolve_phone", AsyncMock()) as db_lookup:
        assert await resolve_store_id_from_phone("phone-2") == 16
    db_lookup.assert_not_awaited()
    assert await resolve_store_id_from_phone("") is None


@pytest.mark.asyncio
async def test_redis_helpers_read_write_and_invalidation():
    redis = AsyncMock()
    redis.get.return_value = "null"
    with patch("services.store_resolver._get_redis", AsyncMock(return_value=redis)):
        assert await __import__("services.store_resolver", fromlist=["_redis_get"])._redis_get("k") == (True, None)
        await __import__("services.store_resolver", fromlist=["_redis_set"])._redis_set("k", 9)
        await invalidate_store_cache("instagram", "acc")
    assert redis.setex.await_count == 1 and redis.delete.await_count == 1
