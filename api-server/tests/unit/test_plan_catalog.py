"""tests/test_plan_catalog.py — Couverture security_overlay/plan_catalog.py.

Couvre :
  - PLAN_CATALOG (structure, codes, prix)
  - CREDIT_TOP_UP_PACKS (structure, IDs)
  - DURATION_OPTIONS
  - _DURATION_DISCOUNTS (remises croissantes)
  - SaaSPlan dataclass
  - CreditTopUpPack dataclass
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")

from security_overlay.models import CreditTopUpPack, SaaSPlan  # noqa: E402
from security_overlay.plan_catalog import (  # noqa: E402
    _DURATION_DISCOUNTS,
    CREDIT_TOP_UP_PACKS,
    DURATION_OPTIONS,
    PLAN_CATALOG,
)

pytestmark = pytest.mark.unit


# ─── Tests PLAN_CATALOG ───────────────────────────────────────────────────────

def test_plan_catalog_non_empty():
    assert len(PLAN_CATALOG) >= 5


def test_plan_catalog_has_free():
    assert "free" in PLAN_CATALOG
    assert PLAN_CATALOG["free"].price_monthly == 0.0


def test_plan_catalog_has_starter():
    assert "starter" in PLAN_CATALOG
    assert PLAN_CATALOG["starter"].price_monthly > 0


def test_plan_catalog_has_enterprise():
    assert "enterprise" in PLAN_CATALOG


def test_plan_catalog_all_codes_match_keys():
    for key, plan in PLAN_CATALOG.items():
        assert plan.code == key, f"Plan code mismatch: key={key}, code={plan.code}"


def test_plan_catalog_prices_non_negative():
    for code, plan in PLAN_CATALOG.items():
        assert plan.price_monthly >= 0, f"Prix négatif pour {code}"


def test_plan_catalog_pro_whatsapp_includes_whatsapp():
    plan = PLAN_CATALOG["pro_whatsapp"]
    assert "channels.whatsapp" in plan.features


def test_plan_catalog_free_has_no_features():
    plan = PLAN_CATALOG["free"]
    assert len(plan.features) == 0


# ─── Tests SaaSPlan dataclass ─────────────────────────────────────────────────

def test_saas_plan_dataclass():
    plan = SaaSPlan(
        code="test_plan",
        name="Test Plan",
        price_monthly=9.99,
        features=["channels.whatsapp", "crm.basic"],
    )
    assert plan.code == "test_plan"
    assert plan.price_monthly == 9.99
    assert "channels.whatsapp" in plan.features


def test_saas_plan_default_features_empty():
    plan = SaaSPlan(code="minimal", name="Minimal")
    assert plan.features == []
    assert plan.price_monthly == 0.0


# ─── Tests CREDIT_TOP_UP_PACKS ────────────────────────────────────────────────

def test_credit_top_up_packs_non_empty():
    assert len(CREDIT_TOP_UP_PACKS) >= 3


def test_credit_top_up_packs_have_required_fields():
    for pack in CREDIT_TOP_UP_PACKS:
        assert pack.pack_id
        assert pack.credits > 0
        assert pack.price > 0
        assert pack.currency


def test_credit_top_up_packs_are_sorted_by_credits():
    credits_list = [p.credits for p in CREDIT_TOP_UP_PACKS]
    assert credits_list == sorted(credits_list), "Packs devrait être triés par crédits croissants"


def test_credit_top_up_pack_dataclass():
    pack = CreditTopUpPack(
        pack_id="test_pack",
        credits=100,
        price=50.0,
        currency="TND",
    )
    assert pack.pack_id == "test_pack"
    assert pack.credits == 100
    assert pack.currency == "TND"


# ─── Tests DURATION_OPTIONS ───────────────────────────────────────────────────

def test_duration_options_contains_monthly():
    assert "monthly" in DURATION_OPTIONS


def test_duration_options_contains_12months():
    assert "12months" in DURATION_OPTIONS


def test_duration_options_at_least_3():
    assert len(DURATION_OPTIONS) >= 3


# ─── Tests _DURATION_DISCOUNTS ────────────────────────────────────────────────

def test_duration_discounts_monthly_no_discount():
    assert _DURATION_DISCOUNTS.get("monthly", 1.0) == 1.0


def test_duration_discounts_12months_has_discount():
    discount = _DURATION_DISCOUNTS.get("12months", 1.0)
    assert discount < 1.0, "12 mois devrait avoir une remise"


def test_duration_discounts_longer_better_deal():
    d_monthly = _DURATION_DISCOUNTS.get("monthly", 1.0)
    d_12 = _DURATION_DISCOUNTS.get("12months", 1.0)
    assert d_12 <= d_monthly
