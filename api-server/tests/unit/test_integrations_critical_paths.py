from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.v1 import integrations as integ
from services.ssrf_guard import SSRFBlocked


def req() -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return Request({"type": "http", "method": "PUT", "path": "/", "headers": [], "query_string": b""}, receive)


def store(extra=None):
    return SimpleNamespace(id=4, stock_api_url="https://stock.example/api", extra_config=extra or {})


def db_for(value):
    db = MagicMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=None)
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


def test_integration_config_url_validator_and_catalog():
    assert integ.IntegrationConfig(url=" https://example.test ").url == "https://example.test"
    with pytest.raises(ValueError):
        integ.IntegrationConfig(url="ftp://bad")
    assert set(integ.INTEGRATION_META) == {"stock_api", "crm_webhook", "catalog_import_url", "order_webhook", "payment_notify_url", "ai_knowledge_url"}


def test_store_integrations_reads_direct_and_extra_config():
    s = store({"stock_api_key_enc": "enc", "stock_api_enabled": False, "integration_crm_webhook": {"url": "https://crm"}})
    result = integ._get_store_integrations(s)
    assert result["stock_api"]["url"] == s.stock_api_url
    assert result["stock_api"]["api_key_enc"] == "enc"
    assert result["stock_api"]["enabled"] is False
    assert result["crm_webhook"]["url"] == "https://crm"
    assert integ._get_store_integrations(SimpleNamespace(stock_api_url=None, extra_config=None)) == {}

@pytest.mark.asyncio
async def test_list_integrations_tenant_and_store_errors_and_success():
    with patch.object(integ, "_sid", return_value=None):
        with pytest.raises(HTTPException) as exc: await integ.list_integrations(db_for(None))
        assert exc.value.status_code == 401
    with patch.object(integ, "_sid", return_value=4):
        with pytest.raises(HTTPException) as exc: await integ.list_integrations(db_for(None))
        assert exc.value.status_code == 404
        result = await integ.list_integrations(db_for(store({"integration_crm_webhook": {"url": "https://crm", "enabled": True, "api_key_enc": "x"}})))
    assert len(result["integrations"]) == 6
    crm = next(x for x in result["integrations"] if x["type"] == "crm_webhook")
    assert crm["api_key_configured"] is True

@pytest.mark.asyncio
async def test_get_integration_validation_and_configured():
    with pytest.raises(HTTPException) as exc:
        await integ.get_integration("unknown", db_for(None))
    assert exc.value.status_code == 404
    with patch.object(integ, "_sid", return_value=4):
        result = await integ.get_integration("stock_api", db_for(store()))
    assert result["url"] == "https://stock.example/api"
    assert result["enabled"] is True

@pytest.mark.asyncio
async def test_set_and_remove_stock_integration():
    s = store({})
    db = db_for(s)
    with patch.object(integ, "_sid", return_value=4), patch.object(integ, "_encrypt_key", return_value="cipher"):
        result = await integ.set_integration("stock_api", integ.IntegrationConfig(url="https://new", api_key="secret", enabled=False), req(), db)
    assert result["api_key_configured"] is True
    assert s.stock_api_url == "https://new"
    assert s.extra_config["stock_api_key_enc"] == "cipher"
    assert s.extra_config["stock_api_enabled"] is False
    with patch.object(integ, "_sid", return_value=4):
        removed = await integ.remove_integration("stock_api", req(), db)
    assert removed["status"] == "removed"
    assert s.stock_api_url is None
    assert db.commit.await_count == 2

@pytest.mark.asyncio
async def test_set_non_stock_preserves_existing_key_and_errors():
    s = store({"integration_crm_webhook": {"url": "https://old", "api_key_enc": "old"}})
    db = db_for(s)
    with patch.object(integ, "_sid", return_value=4):
        result = await integ.set_integration("crm_webhook", integ.IntegrationConfig(url="https://new", enabled=True), req(), db)
    assert result["api_key_configured"] is True
    assert s.extra_config["integration_crm_webhook"]["api_key_enc"] == "old"
    with pytest.raises(HTTPException) as exc:
        await integ.set_integration("bad", integ.IntegrationConfig(url="https://x"), req(), db)
    assert exc.value.status_code == 400

@pytest.mark.asyncio
async def test_test_integration_ssrf_missing_and_http_errors():
    with patch.object(integ, "_sid", return_value=None):
        with pytest.raises(HTTPException) as exc: await integ.test_integration("crm_webhook", db_for(None))
        assert exc.value.status_code == 401
    s = store({})
    with patch.object(integ, "_sid", return_value=4):
        with pytest.raises(HTTPException) as exc: await integ.test_integration("crm_webhook", db_for(s))
        assert exc.value.status_code == 400
    s.extra_config = {"integration_crm_webhook": {"url": "http://127.0.0.1:1"}}
    with patch.object(integ, "_sid", return_value=4), patch("services.ssrf_guard.assert_safe_external_url", side_effect=SSRFBlocked("private")):
        with pytest.raises(HTTPException) as exc: await integ.test_integration("crm_webhook", db_for(s))
        assert exc.value.status_code == 400

@pytest.mark.asyncio
async def test_test_integration_http_success_timeout_connect_and_generic():
    s = store({"integration_crm_webhook": {"url": "https://crm/{question}", "api_key_enc": "enc"}})
    db = db_for(s)
    response = httpx.Response(200, request=httpx.Request("GET", "https://crm/test"))
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(return_value=response)
    with patch.object(integ, "_sid", return_value=4), patch.object(integ, "_decrypt_key", return_value="key"), patch("httpx.AsyncClient", return_value=client), patch("services.ssrf_guard.assert_safe_external_url"):
        result = await integ.test_integration("crm_webhook", db)
    assert result["success"] is True
    assert result["url_tested"] == "https://crm/test"
