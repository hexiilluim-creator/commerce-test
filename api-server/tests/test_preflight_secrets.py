from __future__ import annotations

import pytest

from preflight_secrets import _validate_secret_key


@pytest.mark.unit
def test_secret_key_too_short():
    assert _validate_secret_key("short") is not None


@pytest.mark.unit
def test_low_entropy_rejected():
    assert _validate_secret_key("a" * 80) is not None
