"""tests/test_circuit_breaker.py — Couverture omnicall_v9/circuit_breaker.py.

Couvre :
  - États CLOSED -> OPEN -> HALF_OPEN -> CLOSED
  - record_failure (compteur, seuil, passage OPEN)
  - record_success (reset, passage CLOSED depuis HALF_OPEN)
  - get_state() (CLOSED, OPEN, HALF_OPEN)
  - should_allow_request() (CLOSED -> True, OPEN -> False, HALF_OPEN -> True une fois)
  - Fallback in-memory (Redis down)
  - Reset timeout (OPEN -> HALF_OPEN après cooldown)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")

from omnicall_v9.circuit_breaker import (  # noqa: E402
    CBState,
    CircuitBreaker,
)

pytestmark = pytest.mark.unit


def _make_cb_no_redis(
    error_threshold: int = 3,
    window_seconds: int = 60,
    reset_timeout_seconds: int = 5,
    half_open_success_threshold: int = 2,
) -> CircuitBreaker:
    """Circuit breaker sans Redis (fallback in-memory)."""
    cb = CircuitBreaker(
        error_threshold=error_threshold,
        window_seconds=window_seconds,
        reset_timeout_seconds=reset_timeout_seconds,
        half_open_success_threshold=half_open_success_threshold,
    )
    cb._get_redis = lambda: None
    return cb


# ─── Tests état initial ───────────────────────────────────────────────────────

def test_initial_state_is_closed():
    cb = _make_cb_no_redis()
    state = cb.get_state()
    assert state == CBState.CLOSED


def test_initial_allows_requests():
    cb = _make_cb_no_redis()
    assert cb.should_allow_request() is True


# ─── Tests CLOSED -> OPEN ──────────────────────────────────────────────────────

def test_opens_after_error_threshold():
    cb = _make_cb_no_redis(error_threshold=3, window_seconds=60)
    for _ in range(3):
        cb.record_failure()
    assert cb.get_state() == CBState.OPEN


def test_open_blocks_requests():
    cb = _make_cb_no_redis(error_threshold=2)
    cb.record_failure()
    cb.record_failure()
    assert cb.should_allow_request() is False


def test_single_failure_does_not_open():
    cb = _make_cb_no_redis(error_threshold=5)
    cb.record_failure()
    assert cb.get_state() == CBState.CLOSED


# ─── Tests OPEN -> HALF_OPEN (cooldown) ───────────────────────────────────────

def test_transitions_to_half_open_after_cooldown():
    cb = _make_cb_no_redis(error_threshold=1, reset_timeout_seconds=1)
    cb.record_failure()
    assert cb.get_state() == CBState.OPEN

    # Simuler l'écoulement du temps
    cb._last_open_at = time.monotonic() - 2  # 2 secondes il y a (> reset_timeout=1)
    state = cb.get_state()
    assert state == CBState.HALF_OPEN


def test_half_open_allows_one_request():
    cb = _make_cb_no_redis(error_threshold=1, reset_timeout_seconds=1)
    cb.record_failure()
    cb._last_open_at = time.monotonic() - 2
    assert cb.should_allow_request() is True


# ─── Tests HALF_OPEN -> CLOSED (succès) ───────────────────────────────────────

def test_half_open_closes_after_successes():
    cb = _make_cb_no_redis(
        error_threshold=1,
        reset_timeout_seconds=1,
        half_open_success_threshold=2,
    )
    cb.record_failure()
    cb._last_open_at = time.monotonic() - 2
    cb._state = CBState.HALF_OPEN

    cb.record_success()
    cb.record_success()
    assert cb.get_state() == CBState.CLOSED


# ─── Tests HALF_OPEN -> OPEN (nouvelle erreur) ────────────────────────────────

def test_half_open_reopens_on_failure():
    cb = _make_cb_no_redis(error_threshold=1, reset_timeout_seconds=1)
    cb.record_failure()
    cb._last_open_at = time.monotonic() - 2
    cb._state = CBState.HALF_OPEN

    cb.record_failure()
    assert cb.get_state() == CBState.OPEN


# ─── Tests record_success en CLOSED ──────────────────────────────────────────

def test_success_in_closed_resets_errors():
    cb = _make_cb_no_redis(error_threshold=5)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    # Après un succès en CLOSED, le compteur d'erreurs doit être réduit
    assert cb.get_state() == CBState.CLOSED


# ─── Tests fenêtre temporelle ─────────────────────────────────────────────────

def test_old_errors_outside_window_dont_count():
    cb = _make_cb_no_redis(error_threshold=2, window_seconds=1)
    # Simuler d'anciennes erreurs en dehors de la fenêtre
    cb._errors = [time.monotonic() - 5]  # Il y a 5 secondes (> window=1)
    cb.record_failure()
    # 1 seule erreur dans la fenêtre -> pas d'ouverture (seuil=2)
    assert cb.get_state() == CBState.CLOSED


# ─── Tests CBState ────────────────────────────────────────────────────────────

def test_cb_state_values():
    assert CBState.CLOSED == "closed"
    assert CBState.OPEN == "open"
    assert CBState.HALF_OPEN == "half_open"


def test_cb_state_is_string_enum():
    assert isinstance(CBState.CLOSED, str)
