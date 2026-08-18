"""tests/test_ai_guardrails.py — Tests complets AI Guardrails (crédits IA tenant).

Couvre :
  - _credit_key, _used_key, _allocated_key helpers
  - check_tenant_credit (Redis OK, Redis down, crédit insuffisant)
  - deduct_tenant_credit (atomique, plancher 0)
  - get_tenant_credit_stats (Redis OK, Redis down)
  - init_tenant_credit (nouveau tenant, reset mensuel)
  - Coûts par type (text=1, audio=5, image=10)
  - Fallback in-memory complet
  - Quota par plan (_DEFAULT_QUOTAS)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")

from services.ai_guardrails import (  # noqa: E402
    _DEFAULT_QUOTAS,
    _MEMORY_CREDITS,
    _MEMORY_USED,
    _allocated_key,
    _credit_key,
    _month_suffix,
    _used_key,
    check_tenant_credit,
    deduct_tenant_credit,
    get_tenant_credit_stats,
)

pytestmark = pytest.mark.unit


# ─── Helpers ──────────────────────────────────────────────────────────────────

class _FakeRedis:
    """Redis in-memory minimal pour les tests."""

    def __init__(self, initial: dict | None = None) -> None:
        self._store: dict[str, str] = initial or {}
        self._ttls: dict[str, int] = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value, ex: int | None = None, nx: bool = False):
        if nx and key in self._store:
            return False
        self._store[key] = str(value)
        if ex:
            self._ttls[key] = ex
        return True

    async def setex(self, key: str, ttl: int, value):
        self._store[key] = str(value)
        self._ttls[key] = ttl
        return True

    async def decrby(self, key: str, amount: int):
        current = int(self._store.get(key, 0))
        new_val = max(0, current - amount)
        self._store[key] = str(new_val)
        return new_val

    async def incrby(self, key: str, amount: int):
        current = int(self._store.get(key, 0))
        new_val = current + amount
        self._store[key] = str(new_val)
        return new_val

    async def incr(self, key: str):
        return await self.incrby(key, 1)

    async def exists(self, key: str):
        return 1 if key in self._store else 0

    async def expire(self, key: str, ttl: int):
        self._ttls[key] = ttl
        return True

    async def ping(self):
        return True

    def pipeline(self):
        # AUDIT FIX : le vrai client Redis (redis.asyncio) expose .pipeline()
        # et deduct_tenant_credit()/_ensure_credits_initialized() en
        # dépendent. Son absence ici faisait échouer silencieusement (via
        # `except Exception`) tout le chemin Redis dans deduct_tenant_credit,
        # basculant sur le fallback mémoire sans jamais toucher self._store.
        return _FakePipeline(self)


class _FakePipeline:
    """Pipeline Redis minimal : empile les commandes puis les exécute en ordre."""

    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple]] = []

    def decrby(self, key: str, amount: int):
        self._ops.append(("decrby", (key, amount)))
        return self

    def incrby(self, key: str, amount: int):
        self._ops.append(("incrby", (key, amount)))
        return self

    def set(self, key: str, value, ex: int | None = None, nx: bool = False):
        self._ops.append(("set", (key, value, ex, nx)))
        return self

    async def execute(self):
        results = []
        for name, args in self._ops:
            method = getattr(self._redis, name)
            results.append(await method(*args))
        self._ops.clear()
        return results


# ─── Tests _credit_key / _used_key / _allocated_key ──────────────────────────

def test_credit_key_contains_store_id():
    key = _credit_key(42)
    assert "42" in key
    assert "ai_credits" in key


def test_used_key_contains_store_id():
    key = _used_key(7)
    assert "7" in key


def test_allocated_key_contains_store_id():
    key = _allocated_key(99)
    assert "99" in key


def test_month_suffix_is_yyyymm():
    suffix = _month_suffix()
    assert len(suffix) == 6
    assert suffix.isdigit()


# ─── Tests _DEFAULT_QUOTAS ────────────────────────────────────────────────────

def test_default_quotas_free_is_zero():
    assert _DEFAULT_QUOTAS["free"] == 0


def test_default_quotas_enterprise_is_highest():
    assert _DEFAULT_QUOTAS["enterprise"] >= max(
        v for k, v in _DEFAULT_QUOTAS.items() if k != "enterprise"
    )


def test_default_quotas_all_plans_present():
    required = {"free", "starter", "business", "premium", "pro_whatsapp", "pro", "enterprise"}
    assert required.issubset(_DEFAULT_QUOTAS.keys())


# ─── Tests check_tenant_credit ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_tenant_credit_sufficient_redis():
    """Redis disponible, crédits suffisants -> True.

    AUDIT FIX : ce test ne mockait pas _get_plan_quota, qui fait un vrai
    appel DB. Pour un store_id de test inexistant, ce lookup échouait
    silencieusement et retournait quota=0, faisant échouer check_tenant_credit
    avant même de lire le solde Redis (500) qu'on cherchait à tester.
    """
    store_id = 101
    redis = _FakeRedis({_credit_key(store_id): "500"})

    with patch("services.ai_guardrails._get_redis", AsyncMock(return_value=redis)), \
         patch("services.ai_guardrails._get_plan_quota", AsyncMock(return_value=1000)):
        result = await check_tenant_credit(store_id, cost=10)
    assert result is True


@pytest.mark.asyncio
async def test_check_tenant_credit_insufficient_redis():
    """Redis disponible, crédits insuffisants -> False."""
    store_id = 102
    redis = _FakeRedis({_credit_key(store_id): "5"})

    with patch("services.ai_guardrails._get_redis", AsyncMock(return_value=redis)):
        result = await check_tenant_credit(store_id, cost=10)
    assert result is False


@pytest.mark.asyncio
async def test_check_tenant_credit_redis_down_fallback():
    """Redis indisponible -> fallback in-memory."""
    store_id = 103
    key = _credit_key(store_id)
    _MEMORY_CREDITS[key] = 200

    with patch("services.ai_guardrails._get_redis", AsyncMock(return_value=None)), \
         patch("services.ai_guardrails._get_plan_quota", AsyncMock(return_value=1000)):
        result = await check_tenant_credit(store_id, cost=50)
    assert result is True

    _MEMORY_CREDITS.pop(key, None)


@pytest.mark.asyncio
async def test_check_tenant_credit_zero_cost_always_true():
    """Coût 0 -> toujours autorisé même avec 0 crédits."""
    store_id = 104
    redis = _FakeRedis({_credit_key(store_id): "0"})

    with patch("services.ai_guardrails._get_redis", AsyncMock(return_value=redis)), \
         patch("services.ai_guardrails._get_plan_quota", AsyncMock(return_value=1000)):
        result = await check_tenant_credit(store_id, cost=0)
    assert result is True


# ─── Tests deduct_tenant_credit ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deduct_tenant_credit_redis_ok():
    """Déduction normale avec Redis."""
    store_id = 201
    redis = _FakeRedis({
        _credit_key(store_id): "100",
        _used_key(store_id): "50",
    })

    with patch("services.ai_guardrails._get_redis", AsyncMock(return_value=redis)):
        await deduct_tenant_credit(store_id, cost=10)

    remaining = int(redis._store.get(_credit_key(store_id), 100))
    assert remaining == 90


@pytest.mark.asyncio
async def test_deduct_tenant_credit_floor_at_zero():
    """Déduction ne descend jamais en dessous de 0."""
    store_id = 202
    redis = _FakeRedis({_credit_key(store_id): "3"})

    with patch("services.ai_guardrails._get_redis", AsyncMock(return_value=redis)):
        await deduct_tenant_credit(store_id, cost=10)

    remaining = int(redis._store.get(_credit_key(store_id), 0))
    assert remaining == 0


@pytest.mark.asyncio
async def test_deduct_tenant_credit_fallback_memory():
    """Redis down -> fallback in-memory pour la déduction."""
    store_id = 203
    key = _credit_key(store_id)
    _MEMORY_CREDITS[key] = 80

    with patch("services.ai_guardrails._get_redis", AsyncMock(return_value=None)):
        await deduct_tenant_credit(store_id, cost=20)

    assert _MEMORY_CREDITS.get(key, 80) <= 80
    _MEMORY_CREDITS.pop(key, None)


# ─── Tests get_tenant_credit_stats ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_credit_stats_redis_ok():
    """Stats retournées depuis Redis."""
    store_id = 301
    redis = _FakeRedis({
        _credit_key(store_id): "250",
        _used_key(store_id): "750",
        _allocated_key(store_id): "1000",
    })

    with patch("services.ai_guardrails._get_redis", AsyncMock(return_value=redis)):
        stats = await get_tenant_credit_stats(store_id)

    assert stats["remaining"] == 250
    assert stats["used"] == 750
    assert stats["store_id"] == store_id


@pytest.mark.asyncio
async def test_get_credit_stats_redis_down():
    """Stats retournées depuis in-memory si Redis down."""
    store_id = 302
    key_remaining = _credit_key(store_id)
    key_used = _used_key(store_id)
    _MEMORY_CREDITS[key_remaining] = 100
    _MEMORY_USED[key_used] = 50

    with patch("services.ai_guardrails._get_redis", AsyncMock(return_value=None)):
        stats = await get_tenant_credit_stats(store_id)

    assert "remaining" in stats
    assert "store_id" in stats

    _MEMORY_CREDITS.pop(key_remaining, None)
    _MEMORY_USED.pop(key_used, None)


# ─── Tests coûts par type ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_text_costs_1_credit():
    """Type text = 1 crédit (valeur par défaut)."""
    store_id = 401
    redis = _FakeRedis({_credit_key(store_id): "100"})

    with patch("services.ai_guardrails._get_redis", AsyncMock(return_value=redis)), \
         patch("services.ai_guardrails._get_plan_quota", AsyncMock(return_value=1000)):
        ok = await check_tenant_credit(store_id, cost=1)
    assert ok is True


@pytest.mark.asyncio
async def test_image_costs_10_credits():
    """Type image = 10 crédits — refusé si moins de 10 restants."""
    store_id = 402
    redis = _FakeRedis({_credit_key(store_id): "9"})

    with patch("services.ai_guardrails._get_redis", AsyncMock(return_value=redis)):
        ok = await check_tenant_credit(store_id, cost=10)
    assert ok is False


# ─── Tests isolation temporelle (clé mensuelle) ───────────────────────────────

def test_credit_key_includes_month_suffix():
    """La clé de crédits inclut le mois courant (reset automatique)."""
    key = _credit_key(500)
    suffix = _month_suffix()
    assert suffix in key


def test_keys_different_stores_dont_collide():
    """Les clés de deux stores différents ne se confondent pas."""
    k1 = _credit_key(1)
    k2 = _credit_key(2)
    assert k1 != k2
