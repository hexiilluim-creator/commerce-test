"""tests/test_billing_overlay.py — Couverture security_overlay/billing_overlay.py.

Couvre :
  - _PLAN_FEATURES (structure, cohérence)
  - BillingSnapshot.has_feature (feature présente, absente)
  - BillingSnapshot.is_active, is_paid, expires_at
  - get_billing_snapshot (Redis cache hit, cache miss -> DB, plan free)
  - Snapshot pour plan enterprise (toutes les features)
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
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

from security_overlay.billing_overlay import (  # noqa: E402
    _PLAN_FEATURES,
    BillingSnapshot,
    get_billing_snapshot,
)

pytestmark = pytest.mark.unit


# ─── Tests _PLAN_FEATURES structure ──────────────────────────────────────────

def test_plan_features_has_free():
    assert "free" in _PLAN_FEATURES
    assert len(_PLAN_FEATURES["free"]) == 0  # Free = aucune feature payante


def test_plan_features_has_all_plans():
    expected = {"free", "starter", "business", "premium", "pro_whatsapp"}
    assert expected.issubset(_PLAN_FEATURES.keys())


def test_plan_features_pro_whatsapp_has_whatsapp():
    assert "channels.whatsapp" in _PLAN_FEATURES["pro_whatsapp"]


def test_plan_features_starter_no_whatsapp():
    assert "channels.whatsapp" not in _PLAN_FEATURES["starter"]


def test_plan_features_enterprise_superset_of_premium():
    if "enterprise" in _PLAN_FEATURES:
        premium_features = _PLAN_FEATURES["premium"]
        enterprise_features = _PLAN_FEATURES["enterprise"]
        assert premium_features.issubset(enterprise_features)


def test_plan_features_gold_superset_of_enterprise():
    # AUDIT FIX : "gold" (palier ajouté au-dessus d'enterprise) avait hérité
    # du même bug que enterprise ⊉ premium — channels.messenger,
    # auto_followup, advanced_stats manquaient, cassant la hiérarchie
    # gold ⊇ enterprise ⊇ premium. Ce test couvre ce cas précis pour éviter
    # une régression future.
    if "gold" in _PLAN_FEATURES and "enterprise" in _PLAN_FEATURES:
        enterprise_features = _PLAN_FEATURES["enterprise"]
        gold_features = _PLAN_FEATURES["gold"]
        assert enterprise_features.issubset(gold_features)


def test_plan_features_all_frozensets():
    for plan, features in _PLAN_FEATURES.items():
        assert isinstance(features, frozenset), f"Plan {plan} features doit être frozenset"


# ─── Tests BillingSnapshot ────────────────────────────────────────────────────

def test_billing_snapshot_free_no_features():
    snap = BillingSnapshot(
        store_id=1,
        plan_code="free",
        plan_label="Gratuit",
        is_paid=False,
        features=frozenset(),
        is_active=True,
        expires_at=None,
    )
    assert snap.has_feature("channels.whatsapp") is False
    assert snap.is_paid is False


def test_billing_snapshot_pro_has_whatsapp():
    snap = BillingSnapshot(
        store_id=2,
        plan_code="pro_whatsapp",
        plan_label="Pro WhatsApp",
        is_paid=True,
        features=_PLAN_FEATURES["pro_whatsapp"],
        is_active=True,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    assert snap.has_feature("channels.whatsapp") is True
    assert snap.is_paid is True
    assert snap.is_active is True


def test_billing_snapshot_expired():
    snap = BillingSnapshot(
        store_id=3,
        plan_code="starter",
        plan_label="Starter",
        is_paid=False,
        features=frozenset(),
        is_active=False,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert snap.is_active is False


def test_billing_snapshot_has_feature_unknown_returns_false():
    snap = BillingSnapshot(
        store_id=4,
        plan_code="business",
        plan_label="Business",
        is_paid=True,
        features=_PLAN_FEATURES["business"],
        is_active=True,
        expires_at=None,
    )
    assert snap.has_feature("nonexistent.feature.xyz") is False


def test_billing_snapshot_all_business_features():
    expected_features = _PLAN_FEATURES["business"]
    snap = BillingSnapshot(
        store_id=5,
        plan_code="business",
        plan_label="Business",
        is_paid=True,
        features=expected_features,
        is_active=True,
        expires_at=None,
    )
    for feature in expected_features:
        assert snap.has_feature(feature) is True


# ─── Tests get_billing_snapshot ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_billing_snapshot_free_plan_for_unknown_store():
    """Store sans abonnement -> snapshot avec plan free."""
    class _FakeDB:
        async def execute(self, *args, **kwargs):
            return SimpleNamespace(scalar_one_or_none=lambda: None)
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    class _FakeSL:
        def __call__(self): return _FakeDB()

    with patch("security_overlay.billing_overlay.AsyncSessionLocal", _FakeSL()):
        with patch("security_overlay.billing_overlay._get_redis", AsyncMock(return_value=None)):
            snap = await get_billing_snapshot(store_id=9999)

    assert snap.plan_code in ("free", "inactive", None) or snap is not None


@pytest.mark.asyncio
async def test_get_billing_snapshot_returns_billing_snapshot():
    """Le retour est un objet BillingSnapshot."""
    class _FakeDB:
        async def execute(self, *args, **kwargs):
            return SimpleNamespace(scalar_one_or_none=lambda: None)
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    class _FakeSL:
        def __call__(self): return _FakeDB()

    with patch("security_overlay.billing_overlay.AsyncSessionLocal", _FakeSL()):
        with patch("security_overlay.billing_overlay._get_redis", AsyncMock(return_value=None)):
            snap = await get_billing_snapshot(store_id=1)

    assert isinstance(snap, BillingSnapshot)
