from __future__ import annotations

from services.jwt_rotation import current_rotation_state, encode_jwt, rotate_tokens


def test_jwt_rotate_changes_cutoff():
    token = encode_jwt({"sub": "1"})
    assert token
    before = current_rotation_state()["invalid_before_epoch"]
    result = rotate_tokens(actor="test")
    assert result["invalid_before_epoch"] >= before
