"""tests/test_omnicall_flags.py — Couverture omnicall_v9/flags/registry.py.

Couvre :
  - feature_flag (env "1", "true", "0", absent)
  - get_rollout_pct (0, 50, 100, invalide)
  - get_beta_store_ids (vide, un ID, plusieurs IDs, malformé)
  - should_run_v9_shadow (flag off, flag on, beta store)
  - should_run_v9_active (flag off, flag on, rollout pct, beta)
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

from omnicall_v9.flags.registry import (  # noqa: E402
    OMNICALL_V9_BETA_STORES,
    OMNICALL_V9_ENABLED,
    OMNICALL_V9_ROLLOUT_PCT,
    OMNICALL_V9_SHADOW_MODE,
    feature_flag,
    get_beta_store_ids,
    get_rollout_pct,
    should_run_v9_active,
    should_run_v9_shadow,
)

pytestmark = pytest.mark.unit


# ─── Tests feature_flag ───────────────────────────────────────────────────────

def test_feature_flag_true_when_1(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_ENABLED", "1")
    assert feature_flag(OMNICALL_V9_ENABLED) is True


def test_feature_flag_true_when_true(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_ENABLED", "true")
    assert feature_flag(OMNICALL_V9_ENABLED) is True


def test_feature_flag_true_when_yes(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_ENABLED", "yes")
    assert feature_flag(OMNICALL_V9_ENABLED) is True


def test_feature_flag_false_when_0(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_ENABLED", "0")
    assert feature_flag(OMNICALL_V9_ENABLED) is False


def test_feature_flag_false_when_absent(monkeypatch):
    monkeypatch.delenv("OMNICALL_V9_ENABLED", raising=False)
    assert feature_flag(OMNICALL_V9_ENABLED) is False


def test_feature_flag_false_when_false(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_ENABLED", "false")
    assert feature_flag(OMNICALL_V9_ENABLED) is False


# ─── Tests get_rollout_pct ────────────────────────────────────────────────────

def test_rollout_pct_default_zero(monkeypatch):
    monkeypatch.delenv("OMNICALL_V9_ROLLOUT_PCT", raising=False)
    assert get_rollout_pct() == 0


def test_rollout_pct_50(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_ROLLOUT_PCT", "50")
    assert get_rollout_pct() == 50


def test_rollout_pct_capped_at_100(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_ROLLOUT_PCT", "150")
    assert get_rollout_pct() == 100


def test_rollout_pct_floored_at_0(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_ROLLOUT_PCT", "-10")
    assert get_rollout_pct() == 0


def test_rollout_pct_invalid_string_returns_0(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_ROLLOUT_PCT", "not_a_number")
    assert get_rollout_pct() == 0


# ─── Tests get_beta_store_ids ─────────────────────────────────────────────────

def test_beta_stores_empty_when_absent(monkeypatch):
    monkeypatch.delenv("OMNICALL_V9_BETA_STORES", raising=False)
    assert get_beta_store_ids() == frozenset()


def test_beta_stores_single_id(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_BETA_STORES", "42")
    assert 42 in get_beta_store_ids()


def test_beta_stores_multiple_ids(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_BETA_STORES", "1,2,3,42")
    ids = get_beta_store_ids()
    assert 1 in ids
    assert 2 in ids
    assert 42 in ids


def test_beta_stores_ignores_non_numeric(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_BETA_STORES", "1,abc,3")
    ids = get_beta_store_ids()
    assert 1 in ids
    assert 3 in ids
    assert len(ids) == 2  # abc ignoré


def test_beta_stores_is_frozenset(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_BETA_STORES", "1,2")
    result = get_beta_store_ids()
    assert isinstance(result, frozenset)


# ─── Tests should_run_v9_shadow ──────────────────────────────────────────────

def test_shadow_false_when_flag_off(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_SHADOW_MODE", "0")
    assert should_run_v9_shadow(store_id=1) is False


def test_shadow_true_when_flag_on(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_SHADOW_MODE", "1")
    assert should_run_v9_shadow(store_id=1) is True


def test_shadow_true_for_beta_store(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_SHADOW_MODE", "1")
    monkeypatch.setenv("OMNICALL_V9_BETA_STORES", "99")
    assert should_run_v9_shadow(store_id=99) is True


def test_shadow_no_store_id(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_SHADOW_MODE", "1")
    assert should_run_v9_shadow(store_id=None) is True


# ─── Tests should_run_v9_active ───────────────────────────────────────────────

def test_active_false_when_flag_off(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_ENABLED", "0")
    monkeypatch.setenv("OMNICALL_V9_ROLLOUT_PCT", "100")
    assert should_run_v9_active(store_id=1) is False


def test_active_true_for_beta_store_even_if_rollout_0(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_ENABLED", "1")
    monkeypatch.setenv("OMNICALL_V9_ROLLOUT_PCT", "0")
    monkeypatch.setenv("OMNICALL_V9_BETA_STORES", "77")
    assert should_run_v9_active(store_id=77) is True


def test_active_rollout_100_all_stores(monkeypatch):
    monkeypatch.setenv("OMNICALL_V9_ENABLED", "1")
    monkeypatch.setenv("OMNICALL_V9_ROLLOUT_PCT", "100")
    monkeypatch.delenv("OMNICALL_V9_BETA_STORES", raising=False)
    # Avec 100% rollout, tous les stores doivent être actifs
    assert should_run_v9_active(store_id=12345) is True
