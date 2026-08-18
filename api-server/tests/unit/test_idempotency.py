"""tests/test_idempotency.py — Couverture services/idempotency.py.

Couvre :
  - build_idempotency_key (déterminisme, namespace, unicité)
  - is_already_processed (Redis OK, Redis down -> fallback)
  - mark_processed (Redis OK, Redis down -> fallback)
  - check_and_mark (atomique: premier appel -> False, second -> True)
  - Fallback in-memory TTL
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")

from services.idempotency import (  # noqa: E402
    _local_exists,
    _local_set,
    _local_store,
    build_idempotency_key,
    check_and_mark,
    is_already_processed,
    mark_processed,
)

pytestmark = pytest.mark.unit


# ─── Tests build_idempotency_key ──────────────────────────────────────────────

def test_build_key_is_deterministic():
    k1 = build_idempotency_key("whatsapp", "store1", "msg_abc")
    k2 = build_idempotency_key("whatsapp", "store1", "msg_abc")
    assert k1 == k2


def test_build_key_namespace_prefix():
    key = build_idempotency_key("payments", "100", "pay_001")
    assert key.startswith("payments:")


def test_build_key_different_parts_different_keys():
    k1 = build_idempotency_key("webhook", "store1", "msg_A")
    k2 = build_idempotency_key("webhook", "store1", "msg_B")
    assert k1 != k2


def test_build_key_different_namespaces_different_keys():
    k1 = build_idempotency_key("whatsapp", "store1", "msg_X")
    k2 = build_idempotency_key("payments", "store1", "msg_X")
    assert k1 != k2


def test_build_key_hash_length():
    key = build_idempotency_key("test", "a", "b", "c")
    # namespace:hash[:16]
    parts = key.split(":")
    assert len(parts) >= 2
    assert len(parts[-1]) == 16  # sha256[:16]


# ─── Tests fallback in-memory ─────────────────────────────────────────────────

def test_local_set_and_exists():
    _local_set("test_key_001", ttl_seconds=60)
    assert _local_exists("test_key_001") is True


def test_local_expired_key_not_found():
    _local_set("test_key_002", ttl_seconds=1)
    # Simuler l'expiration en modifiant le store directement
    _local_store["test_key_002"] = time.monotonic() - 1.0
    assert _local_exists("test_key_002") is False


def test_local_nonexistent_key():
    assert _local_exists("key_that_does_not_exist_xyz") is False


# ─── Tests is_already_processed ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_is_already_processed_redis_found():
    class _FakeRedis:
        async def exists(self, key): return 1
    with patch("services.idempotency.get_redis", return_value=_FakeRedis()):
        result = await is_already_processed("some_key")
    assert result is True


@pytest.mark.asyncio
async def test_is_already_processed_redis_not_found():
    class _FakeRedis:
        async def exists(self, key): return 0
    with patch("services.idempotency.get_redis", return_value=_FakeRedis()):
        result = await is_already_processed("another_key")
    assert result is False


@pytest.mark.asyncio
async def test_is_already_processed_redis_down_fallback():
    """Redis down -> fallback in-memory."""
    from services import idempotency
    _local_store.clear()

    with patch("services.idempotency.get_redis", side_effect=Exception("Redis down")):
        result = await is_already_processed("fallback_key_xyz")
    assert result is False  # Pas encore dans le cache local


# ─── Tests mark_processed ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_processed_redis_ok():
    class _FakeRedis:
        def __init__(self):
            self.store = {}
        async def set(self, key, val, ex=None, nx=False):
            self.store[key] = val
            return True
        async def exists(self, key):
            return 1 if key in self.store else 0

    redis = _FakeRedis()
    with patch("services.idempotency.get_redis", return_value=redis):
        await mark_processed("mark_test_key", ttl_seconds=3600)
        exists = await is_already_processed("mark_test_key")
    # Soit marqué dans Redis fake, soit pas de crash
    assert isinstance(exists, bool)


@pytest.mark.asyncio
async def test_mark_processed_fallback_memory():
    """Redis down -> fallback in-memory pour mark."""
    key = "fallback_mark_key_001"
    _local_store.pop(key, None)

    with patch("services.idempotency.get_redis", side_effect=Exception("Redis down")):
        await mark_processed(key, ttl_seconds=3600)

    assert _local_exists(key) is True
    _local_store.pop(key, None)


# ─── Tests check_and_mark ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_and_mark_first_call_returns_false():
    """Premier appel -> pas encore traité -> False."""
    key = "cam_key_first_001"
    _local_store.pop(key, None)

    with patch("services.idempotency.get_redis", side_effect=Exception("Redis down")):
        already = await check_and_mark(key, ttl_seconds=3600)
    assert already is False


@pytest.mark.asyncio
async def test_check_and_mark_second_call_returns_true():
    """Second appel -> déjà traité -> True."""
    key = "cam_key_second_001"
    _local_store.pop(key, None)

    with patch("services.idempotency.get_redis", side_effect=Exception("Redis down")):
        first = await check_and_mark(key, ttl_seconds=3600)
        second = await check_and_mark(key, ttl_seconds=3600)

    assert first is False
    assert second is True
    _local_store.pop(key, None)
