import time
from unittest.mock import MagicMock, patch

import pytest

from omnicall_v9.circuit_breaker import CBState, CircuitBreaker


def test_cb_initial_state():
    cb = CircuitBreaker()
    assert cb.get_state() == CBState.CLOSED
    assert cb.is_v9_safe() is True

def test_cb_opens_after_threshold():
    cb = CircuitBreaker(error_threshold=2, window_seconds=60)
    
    # Mock Redis to avoid connection issues
    with patch.object(cb, '_get_redis', return_value=None):
        cb.record_error()
        assert cb.get_state() == CBState.CLOSED
        
        cb.record_error()
        assert cb.get_state() == CBState.OPEN
        assert cb.is_v9_safe() is False

def test_cb_half_open_cooldown():
    cb = CircuitBreaker(error_threshold=1, reset_timeout_seconds=0.1)
    
    with patch.object(cb, '_get_redis', return_value=None):
        cb.record_error()
        assert cb.get_state() == CBState.OPEN
        
        time.sleep(0.2)
        # Should transition to HALF_OPEN logically
        assert cb.get_state() == CBState.HALF_OPEN
        assert cb.is_v9_safe() is True

def test_cb_half_open_to_closed_success():
    cb = CircuitBreaker(error_threshold=1, reset_timeout_seconds=0.1, half_open_success_threshold=2)
    
    with patch.object(cb, '_get_redis', return_value=None):
        cb.record_error()
        time.sleep(0.2)
        assert cb.is_v9_safe() is True # Transitions to HALF_OPEN internally
        
        cb.record_success()
        assert cb.get_state() == CBState.HALF_OPEN
        
        cb.record_success()
        assert cb.get_state() == CBState.CLOSED

def test_cb_half_open_to_open_failure():
    cb = CircuitBreaker(error_threshold=1, reset_timeout_seconds=0.1)
    
    with patch.object(cb, '_get_redis', return_value=None):
        cb.record_error()
        time.sleep(0.2)
        cb.is_v9_safe() # Force transition to HALF_OPEN
        
        cb.record_error()
        assert cb.get_state() == CBState.OPEN

def test_cb_reset():
    cb = CircuitBreaker(error_threshold=1)
    with patch.object(cb, '_get_redis', return_value=None):
        cb.record_error()
        assert cb.get_state() == CBState.OPEN
        
        cb.reset()
        assert cb.get_state() == CBState.CLOSED
        assert cb.is_v9_safe() is True
