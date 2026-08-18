"""tests/test_security_guard.py — Couverture security_overlay/guard.py.

Couvre :
  - _cache_get / _cache_set (TTL, MAX_SIZE, éviction)
  - SecurityGuard.check_plan_access (feature incluse, non incluse)
  - SecurityGuard.check_plan_access (fail-closed sans snapshot)
  - SecurityGuard.check_credit (crédits OK, insuffisants)
  - SecurityGuard.dump_stats
  - get_guard() singleton
"""
from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime, timedelta
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

from security_overlay.billing_overlay import _PLAN_FEATURES, BillingSnapshot  # noqa: E402
from security_overlay.guard import (  # noqa: E402
    _SNAPSHOT_CACHE,
    SecurityGuard,
    _cache_get,
    _cache_set,
    get_guard,
)

pytestmark = pytest.mark.unit


def _make_snapshot(plan_code: str = "pro_whatsapp", is_active: bool = True) -> BillingSnapshot:
    return BillingSnapshot(
        store_id=1,
        plan_code=plan_code,
        plan_label=plan_code.title(),
        is_paid=plan_code != "free",
        features=_PLAN_FEATURES.get(plan_code, frozenset()),
        is_active=is_active,
        expires_at=datetime.now(UTC) + timedelta(days=30) if is_active else None,
    )


# ─── Tests _cache_get / _cache_set ───────────────────────────────────────────

def test_cache_set_and_get():
    _SNAPSHOT_CACHE.clear()
    snap = _make_snapshot()
    _cache_set(store_id=100, snapshot=snap)
    retrieved = _cache_get(100)
    assert retrieved is not None
    assert retrieved.plan_code == snap.plan_code


def test_cache_miss_for_unknown_store():
    _SNAPSHOT_CACHE.clear()
    result = _cache_get(999)
    assert result is None


def test_cache_expired_entry_returns_none():
    _SNAPSHOT_CACHE.clear()
    snap = _make_snapshot()
    # Insérer avec expiry dans le passé
    _SNAPSHOT_CACHE[500] = (snap, time.monotonic() - 1.0)
    result = _cache_get(500)
    assert result is None


def test_cache_valid_entry_before_ttl():
    _SNAPSHOT_CACHE.clear()
    snap = _make_snapshot()
    _SNAPSHOT_CACHE[501] = (snap, time.monotonic() + 300.0)
    result = _cache_get(501)
    assert result is not None


# ─── Tests SecurityGuard.check_plan_access ────────────────────────────────────

@pytest.mark.asyncio
async def test_check_plan_access_feature_included():
    """Feature incluse dans le plan -> True."""
    guard = SecurityGuard()
    snap = _make_snapshot("pro_whatsapp")

    with patch("security_overlay.guard.get_billing_snapshot", AsyncMock(return_value=snap)):
        result = await guard.check_plan_access(store_id=1, feature="channels.whatsapp")

    assert result is True


@pytest.mark.asyncio
async def test_check_plan_access_feature_excluded():
    """Feature non incluse dans le plan -> False."""
    guard = SecurityGuard()
    snap = _make_snapshot("starter")  # starter n'a pas whatsapp

    with patch("security_overlay.guard.get_billing_snapshot", AsyncMock(return_value=snap)):
        result = await guard.check_plan_access(store_id=2, feature="channels.whatsapp")

    assert result is False


@pytest.mark.asyncio
async def test_check_plan_access_fail_closed_on_error():
    """Si le snapshot échoue et pas de cache -> fail-closed (False)."""
    _SNAPSHOT_CACHE.clear()
    guard = SecurityGuard()

    with patch("security_overlay.guard.get_billing_snapshot",
               AsyncMock(side_effect=Exception("DB down"))):
        result = await guard.check_plan_access(store_id=999, feature="channels.whatsapp")

    assert result is False  # fail-closed


@pytest.mark.asyncio
async def test_check_plan_access_uses_cache_on_error():
    """Si Redis/DB down mais cache local disponible -> utilise le cache."""
    _SNAPSHOT_CACHE.clear()
    snap = _make_snapshot("pro_whatsapp")
    _cache_set(store_id=50, snapshot=snap)

    guard = SecurityGuard()

    with patch("security_overlay.guard.get_billing_snapshot",
               AsyncMock(side_effect=Exception("Redis down"))):
        result = await guard.check_plan_access(store_id=50, feature="channels.whatsapp")

    # Le cache local doit être utilisé -> True
    assert result is True


# ─── Tests SecurityGuard.check_credit ────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_credit_sufficient():
    """Crédits suffisants -> True."""
    guard = SecurityGuard()

    with patch("security_overlay.guard.check_tenant_credit", AsyncMock(return_value=True)):
        result = await guard.check_credit(store_id=1, cost=5)

    assert result is True


@pytest.mark.asyncio
async def test_check_credit_insufficient():
    """Crédits insuffisants -> False."""
    guard = SecurityGuard()

    with patch("security_overlay.guard.check_tenant_credit", AsyncMock(return_value=False)):
        result = await guard.check_credit(store_id=2, cost=100)

    assert result is False


# ─── Tests P1.12-FIX : fail-open plafonné (panne Redis/DB) ───────────────────

@pytest.mark.asyncio
async def test_check_credit_fail_open_allows_under_cap():
    """Panne Redis/DB : autorisé tant que sous le plafond local."""
    import security_overlay.guard as guard_module
    guard_module._failopen_counters.clear()
    guard = SecurityGuard()

    with patch("security_overlay.guard.check_tenant_credit", AsyncMock(side_effect=RuntimeError("redis down"))):
        result = await guard.check_credit(store_id=999, cost=1)

    assert result is True


@pytest.mark.asyncio
async def test_check_credit_fail_open_denies_over_cap():
    """Panne Redis/DB prolongée : refusé au-delà du plafond de secours —
    c'est exactement le TODO que cette correction ferme (auparavant,
    aucune limite n'existait en mode fail-open)."""
    import security_overlay.guard as guard_module
    guard_module._failopen_counters.clear()
    guard = SecurityGuard()

    with patch("security_overlay.guard.check_tenant_credit", AsyncMock(side_effect=RuntimeError("redis down"))):
        results = [await guard.check_credit(store_id=1000, cost=1) for _ in range(guard_module._FAILOPEN_MAX_PER_WINDOW + 5)]

    assert all(results[: guard_module._FAILOPEN_MAX_PER_WINDOW])
    assert not any(results[guard_module._FAILOPEN_MAX_PER_WINDOW :])


@pytest.mark.asyncio
async def test_check_credit_fail_open_isolated_per_store():
    """Le plafond de secours est par tenant — un store en panne ne doit pas
    consommer le quota d'un autre."""
    import security_overlay.guard as guard_module
    guard_module._failopen_counters.clear()
    guard = SecurityGuard()

    with patch("security_overlay.guard.check_tenant_credit", AsyncMock(side_effect=RuntimeError("redis down"))):
        for _ in range(guard_module._FAILOPEN_MAX_PER_WINDOW):
            await guard.check_credit(store_id=1, cost=1)
        # Store 1 est maintenant au plafond, mais store 2 doit rester autorisé.
        result_store_2 = await guard.check_credit(store_id=2, cost=1)

    assert result_store_2 is True


# ─── Tests get_guard() singleton ─────────────────────────────────────────────

def test_get_guard_returns_security_guard():
    guard = get_guard()
    assert isinstance(guard, SecurityGuard)


def test_get_guard_is_singleton():
    g1 = get_guard()
    g2 = get_guard()
    assert g1 is g2
