from __future__ import annotations

from unittest.mock import patch

from omnicall_v9.auto_config import apply_load_balancing, get_dynamic_rollout_limit
from omnicall_v9.circuit_breaker import CBState, CircuitBreaker


def test_rollout_limit_caps_only_under_high_load(monkeypatch):
    monkeypatch.delenv("SYSTEM_LOAD_HIGH", raising=False)
    assert get_dynamic_rollout_limit() == 100
    assert apply_load_balancing(80) == 80
    monkeypatch.setenv("SYSTEM_LOAD_HIGH", "1")
    assert get_dynamic_rollout_limit() == 5
    assert apply_load_balancing(80) == 5
    assert apply_load_balancing(2) == 2


def breaker(**kwargs):
    cb = CircuitBreaker(**kwargs)
    cb._get_redis = lambda: None
    return cb


def test_circuit_opens_at_error_threshold_and_blocks_requests():
    cb = breaker(error_threshold=2, reset_timeout_seconds=300)
    assert cb.is_v9_safe() is True
    cb.record_error()
    assert cb.get_state() == CBState.CLOSED
    cb.record_failure()
    assert cb.get_state() == CBState.OPEN
    assert cb.is_v9_safe() is False
    assert cb.should_allow_request() is False


def test_circuit_enters_half_open_after_timeout_and_closes_after_successes(monkeypatch):
    cb = breaker(error_threshold=1, reset_timeout_seconds=10, half_open_success_threshold=2)
    cb.record_error()
    assert cb.get_state() == CBState.OPEN
    opened_at = cb._last_open_at
    assert opened_at is not None
    with patch("omnicall_v9.circuit_breaker.time.time", return_value=opened_at + 11):
        assert cb.is_v9_safe() is True
        assert cb.get_state() == CBState.HALF_OPEN
        cb.record_success()
        assert cb.get_state() == CBState.HALF_OPEN
        cb.record_success()
    assert cb.get_state() == CBState.CLOSED
    assert cb.is_v9_safe() is True


def test_half_open_failure_returns_to_open():
    cb = breaker(error_threshold=1, reset_timeout_seconds=1, half_open_success_threshold=2)
    cb.record_error()
    opened_at = cb._last_open_at
    assert opened_at is not None
    with patch("omnicall_v9.circuit_breaker.time.time", return_value=opened_at + 2):
        assert cb.is_v9_safe() is True
        cb._state = CBState.HALF_OPEN
        cb.record_error()
    assert cb.get_state() == CBState.OPEN


def test_reset_clears_state_and_errors():
    cb = breaker(error_threshold=1)
    cb.record_error()
    assert cb.get_state() == CBState.OPEN
    cb.reset()
    assert cb.get_state() == CBState.CLOSED
    assert cb.is_v9_safe() is True
    assert cb._errors == []


def test_redis_helpers_fail_safe_when_client_unavailable():
    cb = breaker()
    assert cb._redis_get_state() is None
    assert cb._redis_incr_errors() == 0
    assert cb._redis_get_errors() == 0
    assert cb._redis_get_last_open() is None
    cb._redis_set_state(CBState.OPEN)
    cb._redis_set_last_open(1.0)
    cb._redis_reset_errors()
