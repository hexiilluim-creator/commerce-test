import os
from unittest.mock import patch

import pytest

from omnicall_v9.flags.registry import (
    feature_flag,
    get_beta_store_ids,
    get_rollout_pct,
    should_run_v9_active,
    should_run_v9_shadow,
)


def test_feature_flag_parsing():
    with patch.dict(os.environ, {"TEST_FLAG": "1"}):
        assert feature_flag("TEST_FLAG") is True
    with patch.dict(os.environ, {"TEST_FLAG": "true"}):
        assert feature_flag("TEST_FLAG") is True
    with patch.dict(os.environ, {"TEST_FLAG": "0"}):
        assert feature_flag("TEST_FLAG") is False
    with patch.dict(os.environ, {"TEST_FLAG": "random"}):
        assert feature_flag("TEST_FLAG") is False

def test_get_rollout_pct():
    with patch.dict(os.environ, {"OMNICALL_V9_ROLLOUT_PCT": "42"}):
        assert get_rollout_pct() == 42
    with patch.dict(os.environ, {"OMNICALL_V9_ROLLOUT_PCT": "invalid"}):
        assert get_rollout_pct() == 0
    with patch.dict(os.environ, {"OMNICALL_V9_ROLLOUT_PCT": "150"}):
        assert get_rollout_pct() == 100

def test_get_beta_store_ids():
    with patch.dict(os.environ, {"OMNICALL_V9_BETA_STORES": "1, 2, 3, invalid, 4"}):
        ids = get_beta_store_ids()
        assert ids == frozenset({1, 2, 3, 4})

def test_should_run_v9_shadow():
    with patch.dict(os.environ, {"OMNICALL_V9_SHADOW_MODE": "1"}):
        assert should_run_v9_shadow() is True
    with patch.dict(os.environ, {"OMNICALL_V9_SHADOW_MODE": "0"}):
        assert should_run_v9_shadow() is False

def test_should_run_v9_active_rollout():
    with patch.dict(os.environ, {
        "OMNICALL_V9_ENABLED": "1",
        "OMNICALL_V9_ROLLOUT_PCT": "50",
        "OMNICALL_V9_BETA_STORES": "10"
    }):
        # Beta store always runs
        assert should_run_v9_active(10) is True
        
        # Non-beta store depends on hash
        # We test both cases if possible, or just check it returns a bool
        res = should_run_v9_active(1)
        assert isinstance(res, bool)

def test_should_run_v9_active_disabled():
    with patch.dict(os.environ, {"OMNICALL_V9_ENABLED": "0"}):
        assert should_run_v9_active(10) is False
