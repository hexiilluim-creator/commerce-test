"""Regression tests for runtime alignment fixes.

Covers:
  - /metrics bypass at TenantMiddleware level (route-level token guard stays active)
  - canonical credit pack catalog returned by billing endpoints
  - dashboard-compatible credit usage payload normalization
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
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-chars-minimum-ok!")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token-001")

from api.v1.credits import (  # noqa: E402
    _normalize_usage_payload,
    _rows_use_canonical_pack_codes,
    _serialize_static_packs,
)
from middleware.tenant import PUBLIC_EXACT  # noqa: E402
from security_overlay.models import CreditTopUpPackModel  # noqa: E402

pytestmark = pytest.mark.unit


def test_metrics_path_is_public_for_jwt_bypass_only():
    assert "/metrics" in PUBLIC_EXACT
    assert "/metrics/" in PUBLIC_EXACT


def test_static_packs_use_canonical_codes_expected_by_purchase_service():
    packs = _serialize_static_packs()
    codes = [pack["pack_code"] for pack in packs]
    assert codes == ["starter_50", "growth_200", "business_500", "enterprise_1k"]
    assert all(pack["credits_amount"] > 0 for pack in packs)
    assert all(pack["price_dt"] > 0 for pack in packs)


def test_rows_use_canonical_pack_codes_rejects_legacy_seed_values():
    legacy_rows = [
        CreditTopUpPackModel(pack_code="top_up_1k", display_name="legacy", credits_amount=1000, price_dt=5.0, price_usd=1.65, bonus_credits=0, is_active=True, rank=10),
    ]
    assert _rows_use_canonical_pack_codes(legacy_rows) is False


def test_rows_use_canonical_pack_codes_accepts_supported_values():
    rows = [
        CreditTopUpPackModel(pack_code="starter_50", display_name="50 crédits IA", credits_amount=50, price_dt=25.0, price_usd=8.25, bonus_credits=0, is_active=True, rank=10),
        CreditTopUpPackModel(pack_code="growth_200", display_name="200 crédits IA", credits_amount=200, price_dt=80.0, price_usd=26.40, bonus_credits=0, is_active=True, rank=20),
    ]
    assert _rows_use_canonical_pack_codes(rows) is True


def test_normalize_usage_payload_produces_dashboard_fields():
    summary = {
        "plan_code": "starter",
        "credits_monthly_limit": 500,
        "credits_used": 125,
        "credits_remaining": 375,
        "reset_date": "2026-08-01T00:00:00+00:00",
    }
    stats = {
        "allocated": 500,
        "used": 125,
        "remaining": 375,
        "credits_percent_used": 25.0,
        "period": "2026-07",
    }

    payload = _normalize_usage_payload(summary, stats)

    assert payload["has_active_period"] is True
    assert payload["ai_credits_allocated"] == 500
    assert payload["ai_credits_used"] == 125
    assert payload["ai_credits_remaining"] == 375
    assert payload["usage_pct"] == 25.0
    assert payload["is_ai_blocked"] is False
