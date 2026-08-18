from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request
from starlette.responses import Response

from middleware.input_validation import (
    InputValidationMiddleware,
    _check_path,
    _check_query_string,
)


def request(path="/api/items", method="GET", query="", headers=None):
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query.encode(),
            "headers": raw_headers,
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


def body(response):
    return response.body


def test_query_and_path_helpers_detect_expected_threats():
    assert _check_query_string("q=SELECT%20*%20FROM%20users") == "sql_injection"
    assert _check_query_string("next=<script>alert(1)</script>") == "xss"
    assert _check_query_string("file=../../etc/passwd") == "path_traversal"
    assert _check_query_string("q=normal") is None
    assert _check_path("/api/../secret") == "path_traversal"
    assert _check_path("/api/%00") == "null_byte_injection"
    assert _check_path("/api/items") is None


@pytest.mark.asyncio
async def test_dispatch_allows_clean_request():
    mw = InputValidationMiddleware(AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))
    response = await mw.dispatch(request(), call_next)
    assert response.status_code == 200
    call_next.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/../secret", "/api/%00"])
async def test_dispatch_blocks_malicious_path(path):
    mw = InputValidationMiddleware(AsyncMock())
    call_next = AsyncMock()
    response = await mw.dispatch(request(path=path), call_next)
    assert response.status_code == 400
    call_next.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["q=SELECT+1", "x=<script>alert(1)</script>", "f=../../etc"])
async def test_dispatch_blocks_malicious_query(query):
    mw = InputValidationMiddleware(AsyncMock())
    call_next = AsyncMock()
    response = await mw.dispatch(request(query=query), call_next)
    assert response.status_code == 400
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_blocks_scanner_user_agent():
    mw = InputValidationMiddleware(AsyncMock())
    response = await mw.dispatch(request(headers={"user-agent": "sqlmap/1.8"}), AsyncMock())
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_dispatch_blocks_unsupported_body_content_type():
    mw = InputValidationMiddleware(AsyncMock())
    response = await mw.dispatch(
        request(method="POST", headers={"content-type": "application/xml"}), AsyncMock()
    )
    assert response.status_code == 415


@pytest.mark.asyncio
async def test_dispatch_allows_supported_content_type_with_parameters():
    mw = InputValidationMiddleware(AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    response = await mw.dispatch(
        request(method="POST", headers={"content-type": "application/json; charset=utf-8"}), call_next
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dispatch_blocks_injected_forwarded_header():
    mw = InputValidationMiddleware(AsyncMock())
    response = await mw.dispatch(
        request(headers={"x-forwarded-for": "<script>alert(1)</script>"}), AsyncMock()
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_dispatch_exempts_webhook_and_health_paths():
    mw = InputValidationMiddleware(AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    for path in ("/health", "/api/v1/payments/webhook", "/metrics"):
        response = await mw.dispatch(request(path=path, query="q=SELECT+1"), call_next)
        assert response.status_code == 200
    assert call_next.await_count == 3
