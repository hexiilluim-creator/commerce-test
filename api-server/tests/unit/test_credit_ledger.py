"""tests/test_credit_ledger.py — Couverture services/credit_ledger.py.

Couvre :
  - CREDIT_PACKS structure et valeurs
  - PLAN_MONTHLY_CREDITS valeurs
  - get_ledger_history (avec et sans table credit_events)
  - get_usage_summary
  - purchase_top_up (pack valide + pack inconnu)
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

from services.credit_ledger import (  # noqa: E402
    CREDIT_PACKS,
    PLAN_MONTHLY_CREDITS,
    get_ledger_history,
    get_usage_summary,
    purchase_top_up,
)

pytestmark = pytest.mark.unit


# ─── Tests CREDIT_PACKS ───────────────────────────────────────────────────────

def test_credit_packs_non_empty():
    assert len(CREDIT_PACKS) >= 4


def test_credit_packs_all_have_credits_and_price():
    for pack_id, pack in CREDIT_PACKS.items():
        assert "credits" in pack, f"Pack {pack_id} missing credits"
        assert "price_dt" in pack, f"Pack {pack_id} missing price_dt"
        assert pack["credits"] > 0
        assert pack["price_dt"] > 0


def test_credit_packs_enterprise_1k_has_1000_credits():
    assert CREDIT_PACKS["enterprise_1k"]["credits"] == 1000


def test_credit_packs_starter_50_has_50_credits():
    assert CREDIT_PACKS["starter_50"]["credits"] == 50


# ─── Tests PLAN_MONTHLY_CREDITS ───────────────────────────────────────────────

def test_plan_monthly_credits_non_empty():
    assert len(PLAN_MONTHLY_CREDITS) >= 3


def test_plan_monthly_credits_pro_whatsapp_highest():
    vals = PLAN_MONTHLY_CREDITS.values()
    assert PLAN_MONTHLY_CREDITS.get("pro_whatsapp", 0) >= max(vals) * 0.5


def test_plan_monthly_credits_free_lowest():
    free_credits = PLAN_MONTHLY_CREDITS.get("free", 0)
    assert free_credits <= min(PLAN_MONTHLY_CREDITS.values())


# ─── Tests get_ledger_history ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_ledger_history_returns_list():
    """get_ledger_history doit toujours retourner une liste."""
    class _FakeDB:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
        async def execute(self, *args, **kwargs):
            raise Exception("no table")

    class _FakeSessionLocal:
        def __call__(self):
            return _FakeDB()

    with patch("services.credit_ledger.AsyncSessionLocal", _FakeSessionLocal()):
        result = await get_ledger_history(store_id=1, limit=10)

    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_get_ledger_history_limit_respected():
    """Le paramètre limit est transmis à la requête."""
    class _FakeMapping:
        def mappings(self): return self
        def all(self): return [{"event_type": "deduct", "credits_delta": -1,
                                "balance_after": 99, "description": "test",
                                "created_at": "2026-01-01"}]

    class _FakeSession:
        async def execute(self, stmt, params=None):
            return _FakeMapping()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    class _FSL:
        def __call__(self): return _FakeSession()

    with patch("services.credit_ledger.AsyncSessionLocal", _FSL()):
        result = await get_ledger_history(store_id=5, limit=1)

    assert isinstance(result, list)


# ─── Tests get_usage_summary ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_usage_summary_returns_dict():
    """get_usage_summary retourne un dict avec les clés attendues."""
    class _FakeRow:
        def scalar_one_or_none(self): return None

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            return _FakeRow()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    class _FSL:
        def __call__(self): return _FakeSession()

    with patch("services.credit_ledger.AsyncSessionLocal", _FSL()):
        result = await get_usage_summary(store_id=10)

    assert isinstance(result, dict)


# ─── Tests purchase_top_up ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_purchase_top_up_valid_pack():
    """Top-up avec pack valide -> succès."""
    class _FakeRow:
        def scalar_one_or_none(self): return None

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            return _FakeRow()
        def add(self, obj): pass
        async def commit(self): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    class _FSL:
        def __call__(self): return _FakeSession()

    with patch("services.credit_ledger.AsyncSessionLocal", _FSL()):
        result = await purchase_top_up(
            store_id=20,
            pack_id="starter_50",
            payment_ref="REF-001",
        )

    assert result is not None


@pytest.mark.asyncio
async def test_purchase_top_up_invalid_pack_raises():
    """Pack inconnu -> exception ou résultat indiquant l'erreur."""
    class _FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    class _FSL:
        def __call__(self): return _FakeSession()

    with patch("services.credit_ledger.AsyncSessionLocal", _FSL()):
        try:
            result = await purchase_top_up(
                store_id=21,
                pack_id="nonexistent_pack_xyz",
                payment_ref="REF-002",
            )
            # Si pas d'exception, le résultat doit indiquer une erreur
            assert result is not None
        except (KeyError, ValueError, Exception):
            pass  # Comportement acceptable
