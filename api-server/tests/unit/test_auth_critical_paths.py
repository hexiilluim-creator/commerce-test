from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.v1 import auth


def test_password_hash_round_trip_and_invalid_hash_fail_closed():
    hashed = auth.hash_password("SecurePass123")
    assert auth.verify_password("SecurePass123", hashed) is True
    assert auth.verify_password("WrongPass123", hashed) is False
    assert auth.verify_password("SecurePass123", "not-a-bcrypt-hash") is False


def test_password_hash_truncates_long_utf8_input_safely():
    hashed = auth.hash_password("A1" + "x" * 200)
    assert auth.verify_password("A1" + "x" * 200, hashed) is True
    assert auth.verify_password("B1" + "x" * 200, hashed) is False


def test_register_and_reset_password_complexity_validators():
    register = auth.RegisterRequest(email="user@example.com", password="Password123", store_name="Store")
    assert register.password == "Password123"
    with pytest.raises(ValueError):
        auth.RegisterRequest(email="user@example.com", password="onlyletters", store_name="Store")
    with pytest.raises(ValueError):
        auth.RegisterRequest(email="user@example.com", password="12345678", store_name="Store")
    with pytest.raises(ValueError):
        auth.ResetPasswordRequest(token="t", new_password="onlyletters", confirm_password="onlyletters")


def test_secure_cookie_switches_with_environment():
    with patch.object(auth.settings, "ENV", "production"):
        assert auth._secure_cookie_enabled() is True
    with patch.object(auth.settings, "ENV", "development"):
        assert auth._secure_cookie_enabled() is False


def test_set_and_clear_auth_cookie_apply_secure_attributes():
    response = MagicMock()
    with patch.object(auth.settings, "ENV", "staging"):
        auth._set_auth_cookie(response, "access")
        auth._clear_auth_cookie(response)
    calls = response.set_cookie.call_args_list
    assert calls[0].kwargs["httponly"] is True
    assert calls[0].kwargs["secure"] is True
    assert calls[0].kwargs["path"] == "/api"
    assert calls[1].kwargs["max_age"] == 0


def test_create_access_and_refresh_tokens_include_expected_claims():
    with patch("services.jwt_rotation.encode_jwt", side_effect=lambda payload, algorithm: payload):
        access = auth.create_token(4, "admin", user_id=9)
        refresh = auth.create_refresh_token(4, "admin", user_id=9)
    assert access["store_id"] == 4
    assert access["user_id"] == 9
    assert refresh["type"] == "refresh"
    assert refresh["jti"]


@pytest.mark.asyncio
async def test_token_invalidation_writes_and_reads_redis_timestamp():
    redis = AsyncMock()
    redis.get.return_value = "200"
    with patch("api.v1.auth.get_redis", return_value=redis):
        with patch("api.v1.auth.time.time", return_value=200):
            await auth._invalidate_user_tokens(9)
        assert await auth._is_token_invalidated(9, 200) is True
        assert await auth._is_token_invalidated(9, 201) is False
    redis.setex.assert_awaited_once()


@pytest.mark.asyncio
async def test_token_invalidation_fails_open_when_redis_unavailable():
    redis = AsyncMock()
    redis.get.side_effect = RuntimeError("redis down")
    with patch("api.v1.auth.get_redis", return_value=redis):
        assert await auth._is_token_invalidated(9, 1) is False


@pytest.mark.asyncio
async def test_current_user_reads_bearer_and_returns_active_user():
    request = MagicMock()
    request.cookies = {}
    request.headers = {"Authorization": "Bearer token"}
    user = SimpleNamespace(id=9, is_active=True)
    result = SimpleNamespace(scalar_one_or_none=lambda: user)
    db = AsyncMock()
    db.execute.return_value = result
    with patch("services.jwt_rotation.decode_jwt", return_value={"user_id": 9, "iat": 300}), patch(
        "api.v1.auth._is_token_invalidated", new=AsyncMock(return_value=False)
    ):
        resolved = await auth._get_current_user_from_request(request, db)
    assert resolved is user


@pytest.mark.asyncio
async def test_current_user_requires_token_and_rejects_invalidated_session():
    request = MagicMock()
    request.cookies = {}
    request.headers = {}
    db = AsyncMock()
    with pytest.raises(HTTPException) as missing:
        await auth._get_current_user_from_request(request, db)
    assert missing.value.status_code == 401

    request.headers = {"Authorization": "Bearer token"}
    with patch("services.jwt_rotation.decode_jwt", return_value={"user_id": 9, "iat": 300}), patch(
        "api.v1.auth._is_token_invalidated", new=AsyncMock(return_value=True)
    ):
        with pytest.raises(HTTPException) as invalidated:
            await auth._get_current_user_from_request(request, db)
    assert invalidated.value.status_code == 401
