"""tests/test_paymee_provider.py — Tests Provider Paymee (Phase 3).

Tests : 20 cas
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")
os.environ.setdefault("ENV", "test")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-chars-minimum-ok!")
os.environ.setdefault("SERVER_DOMAIN", "https://test.example.com")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-00000000000000000000000000000000000000000000000000")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token-001")

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestPaymeeProvider:

    def _make_provider(self, cfg=None):
        cfg = cfg or {"api_key": "test-key", "vendor_id": "12345"}
        # Import inline pour éviter les effets de bord au chargement
        import importlib
        pf = importlib.import_module("services.payment_factory")
        return pf.PaymeeProvider(cfg)

    def test_name(self):
        p = self._make_provider()
        assert p.name == "paymee"

    @pytest.mark.asyncio
    async def test_create_payment_link_missing_api_key(self):
        from fastapi import HTTPException
        p = self._make_provider({"vendor_id": "12345"})
        with pytest.raises(HTTPException) as exc_info:
            await p.create_payment_link(100.0)
        assert exc_info.value.status_code == 400
        assert "api_key" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_create_payment_link_missing_vendor_id(self):
        from fastapi import HTTPException
        p = self._make_provider({"api_key": "key"})
        with pytest.raises(HTTPException) as exc_info:
            await p.create_payment_link(100.0)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_payment_link_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": True,
            "data": {"token": "pay-token-abc123"}
        }
        with patch("services.payment_factory._http_request_with_retry", return_value=mock_resp):
            p = self._make_provider()
            result = await p.create_payment_link(150.500, description="Test", reference="ORD-001")
        assert result["provider"] == "paymee"
        assert "pay-token-abc123" in result["url"]
        assert result["id"] == "pay-token-abc123"

    @pytest.mark.asyncio
    async def test_create_payment_link_api_error_502(self):
        from fastapi import HTTPException
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        with patch("services.payment_factory._http_request_with_retry", return_value=mock_resp):
            p = self._make_provider()
            with pytest.raises(HTTPException) as exc_info:
                await p.create_payment_link(100.0)
            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_create_payment_link_invalid_response_502(self):
        from fastapi import HTTPException
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": False}  # pas de token
        with patch("services.payment_factory._http_request_with_retry", return_value=mock_resp):
            p = self._make_provider()
            with pytest.raises(HTTPException) as exc_info:
                await p.create_payment_link(100.0)
            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_verify_payment_paid(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"payment_status": "completed"}}
        with patch("services.payment_factory._http_request_with_retry", return_value=mock_resp):
            p = self._make_provider()
            result = await p.verify_payment("token-123")
        assert result["status"] == "paid"
        assert result["provider"] == "paymee"

    @pytest.mark.asyncio
    async def test_verify_payment_failed(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"payment_status": "failed"}}
        with patch("services.payment_factory._http_request_with_retry", return_value=mock_resp):
            p = self._make_provider()
            result = await p.verify_payment("token-123")
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_verify_payment_pending(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"payment_status": "processing"}}
        with patch("services.payment_factory._http_request_with_retry", return_value=mock_resp):
            p = self._make_provider()
            result = await p.verify_payment("token-123")
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_verify_payment_http_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("services.payment_factory._http_request_with_retry", return_value=mock_resp):
            p = self._make_provider()
            result = await p.verify_payment("bad-token")
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_verify_payment_missing_api_key(self):
        from fastapi import HTTPException
        p = self._make_provider({"vendor_id": "12345"})
        with pytest.raises(HTTPException) as exc_info:
            await p.verify_payment("token")
        assert exc_info.value.status_code == 400

    def test_paymee_in_registry(self):
        import importlib
        pf = importlib.import_module("services.payment_factory")
        assert "paymee" in pf._PROVIDER_REGISTRY

    def test_factory_get_paymee(self):
        import importlib
        pf = importlib.import_module("services.payment_factory")
        provider = pf.PaymentFactory.get("paymee", {"api_key": "k", "vendor_id": "1"})
        assert provider.name == "paymee"

    @pytest.mark.asyncio
    async def test_create_link_with_phone(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": True, "data": {"token": "tok"}}
        with patch("services.payment_factory._http_request_with_retry", return_value=mock_resp) as mock_req:
            p = self._make_provider()
            await p.create_payment_link(50.0, customer_phone="+21698000000")
            call_kwargs = mock_req.call_args
            payload = call_kwargs[1].get("json_payload") or call_kwargs[0][2]
            assert payload.get("phone") == "+21698000000"
