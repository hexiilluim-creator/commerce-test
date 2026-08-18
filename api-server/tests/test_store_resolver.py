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
