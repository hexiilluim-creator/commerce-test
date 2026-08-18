from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request
from starlette.responses import Response

from middleware import csrf_protection as csrf


@pytest.fixture(autouse=True)
def disable_automatic_test_bypass(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ENV", "development")
    original_getenv = csrf.os.getenv
    monkeypatch.setattr(
        csrf.os,
        "getenv",
        lambda key, default=None: None if key == "PYTEST_CURRENT_TEST" else original_getenv(key, default),
    )



def make_request(path="/api/orders", method="POST", headers=None, cookie=None):
    values = dict(headers or {})
    if cookie is not None:
        values["cookie"] = f"{csrf.CSRF_COOKIE_NAME}={cookie}"
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in values.items()]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": raw_headers,
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


def test_generate_and_verify_token_round_trip():
    token = csrf._generate_csrf_token("session-1")
    assert csrf._verify_csrf_token(token) is True
    assert len(token.split(".")) == 4


def test_verify_rejects_empty_malformed_and_tampered_tokens():
    assert csrf._verify_csrf_token("") is False
    assert csrf._verify_csrf_token("bad.token") is False
    token = csrf._generate_csrf_token()
    assert csrf._verify_csrf_token(token + "x") is False
    parts = token.split(".")
    parts[-1] = "0" * len(parts[-1])
    assert csrf._verify_csrf_token(".".join(parts)) is False


def test_verify_rejects_expired_token(monkeypatch):
    token = csrf._generate_csrf_token()
    timestamp = int(token.split(".")[0])
    monkeypatch.setattr(csrf.time, "time", lambda: timestamp + csrf.CSRF_TOKEN_MAX_AGE + 1)
    assert csrf._verify_csrf_token(token) is False


@pytest.mark.asyncio
async def test_safe_method_get_calls_next_and_sets_cookie_when_missing():
    mw = csrf.CSRFProtectionMiddleware(AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    response = await mw.dispatch(make_request(method="GET"), call_next)
    assert response.status_code == 200
    assert "csrf_token=" in response.headers.get("set-cookie", "")
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_exempt_auth_path_calls_next_without_csrf_header():
    mw = csrf.CSRFProtectionMiddleware(AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    response = await mw.dispatch(make_request(path="/api/v1/auth/login"), call_next)
    assert response.status_code == 200
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_exempt_webhook_prefix_calls_next():
    mw = csrf.CSRFProtectionMiddleware(AsyncMock())
    response = await mw.dispatch(
        make_request(path="/api/v1/payments/webhook/provider"), AsyncMock(return_value=Response("ok"))
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_write_request_without_tokens_is_rejected():
    mw = csrf.CSRFProtectionMiddleware(AsyncMock())
    call_next = AsyncMock()
    response = await mw.dispatch(make_request(), call_next)
    assert response.status_code == 403
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_request_with_mismatched_tokens_is_rejected():
    mw = csrf.CSRFProtectionMiddleware(AsyncMock())
    response = await mw.dispatch(
        make_request(headers={csrf.CSRF_HEADER_NAME: "header"}, cookie="cookie"), AsyncMock()
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_write_request_with_invalid_token_is_rejected():
    mw = csrf.CSRFProtectionMiddleware(AsyncMock())
    response = await mw.dispatch(
        make_request(headers={csrf.CSRF_HEADER_NAME: "bad.token"}, cookie="bad.token"), AsyncMock()
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_valid_write_request_rotates_token():
    token = csrf._generate_csrf_token()
    mw = csrf.CSRFProtectionMiddleware(AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    response = await mw.dispatch(
        make_request(headers={csrf.CSRF_HEADER_NAME: token}, cookie=token), call_next
    )
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "csrf_token=" in set_cookie
    assert "Max-Age=3600" in set_cookie
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_test_environment_bypass_calls_next():
    mw = csrf.CSRFProtectionMiddleware(AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("ENV", "test")
        response = await mw.dispatch(make_request(), call_next)
    assert response.status_code == 200
    call_next.assert_awaited_once()
