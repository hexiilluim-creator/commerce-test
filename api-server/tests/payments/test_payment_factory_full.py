"""Tests complémentaires pour services/payment_factory.py — couverture des chemins non-testés."""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services.payment_factory import (
    CashProvider,
    FlouciProvider,
    KonnectProvider,
    PaymeeProvider,
    PaymentFactory,
    StripeProvider,
)


@pytest.mark.payments
class TestFlouciProviderExtra:
    """Tests complémentaires FlouciProvider."""

    def test_init_with_config_dict(self):
        provider = FlouciProvider({"webhook_secret": "test-secret", "api_key": "test-key"})
        assert provider.cfg["webhook_secret"] == "test-secret"
        assert provider.cfg["api_key"] == "test-key"

    def test_init_with_empty_config(self):
        provider = FlouciProvider({})
        assert provider.cfg == {}

    def test_verify_signature_missing_header(self):
        provider = FlouciProvider({"webhook_secret": "secret"})
        payload = b'{"test": "data"}'
        ok, status = provider.verify_webhook_signature(payload, {})
        assert ok is False

    def test_verify_signature_empty_payload(self):
        provider = FlouciProvider({"webhook_secret": "secret"})
        ok, status = provider.verify_webhook_signature(b"", {"x-flouci-signature": "abc"})
        assert ok is False

    def test_name_attribute(self):
        provider = FlouciProvider({})
        assert provider.name == "flouci"


@pytest.mark.payments
class TestKonnectProviderExtra:
    """Tests complémentaires KonnectProvider."""

    def test_init_with_config_dict(self):
        provider = KonnectProvider({"webhook_secret": "test-secret"})
        assert provider.cfg["webhook_secret"] == "test-secret"

    def test_verify_signature_header_variants(self):
        provider = KonnectProvider({"webhook_secret": "secret"})
        payload = b'{"test": "data"}'
        digest = hmac.new(b"secret", payload, hashlib.sha256).hexdigest()
        ok, status = provider.verify_webhook_signature(payload, {"x-signature": digest})
        assert ok is True
        assert status == "verified"

    def test_name_attribute(self):
        provider = KonnectProvider({})
        assert provider.name == "konnect"


@pytest.mark.payments
class TestPaymeeProviderExtra:
    """Tests complémentaires PaymeeProvider."""

    def test_checksum_with_integer_amount(self):
        provider = PaymeeProvider({"api_key": "test-key"})
        payload = json.dumps({
            "check_sum": "invalid",
            "token": "token123",
            "amount": 100
        }).encode()
        ok, status = provider.verify_webhook_signature(payload, {})
        assert ok is False

    def test_checksum_with_string_amount(self):
        provider = PaymeeProvider({"api_key": "test-key"})
        payload = json.dumps({
            "check_sum": "invalid",
            "token": "token123",
            "amount": "50.00"
        }).encode()
        ok, status = provider.verify_webhook_signature(payload, {})
        assert ok is False

    def test_name_attribute(self):
        provider = PaymeeProvider({})
        assert provider.name == "paymee"


@pytest.mark.payments
class TestStripeProviderExtra:
    """Tests complémentaires StripeProvider."""

    def test_init_with_config(self):
        provider = StripeProvider({"webhook_secret": "whsec_test123"})
        assert provider.cfg["webhook_secret"] == "whsec_test123"

    def test_init_with_empty_config(self):
        provider = StripeProvider({})
        assert provider.cfg == {}

    def test_name_attribute(self):
        provider = StripeProvider({})
        assert provider.name == "stripe"


@pytest.mark.payments
class TestCashProviderExtra:
    """Tests complémentaires CashProvider."""

    def test_verify_returns_not_applicable(self):
        provider = CashProvider({})
        ok, status = provider.verify_webhook_signature(b"any-payload", {})
        assert ok is True
        assert status == "not_applicable"

    def test_name(self):
        provider = CashProvider({})
        assert provider.name == "cash"

    @pytest.mark.asyncio
    async def test_create_payment_link(self):
        provider = CashProvider({})
        result = await provider.create_payment_link(100.0, "TND", reference="ref-123")
        assert result["provider"] == "cash"
        assert result["method"] == "cash"
        assert result["instruction"] == "Paiement à la livraison"

    @pytest.mark.asyncio
    async def test_verify_payment_pending(self):
        provider = CashProvider({})
        result = await provider.verify_payment("ref-123")
        assert result["status"] == "pending_cash"


@pytest.mark.payments
class TestPaymentFactoryGet:
    """Tests pour PaymentFactory.get()."""

    def test_get_flouci_provider(self):
        provider = PaymentFactory.get("flouci", {"webhook_secret": "test"})
        assert isinstance(provider, FlouciProvider)

    def test_get_konnect_provider(self):
        provider = PaymentFactory.get("konnect", {"webhook_secret": "test"})
        assert isinstance(provider, KonnectProvider)

    def test_get_paymee_provider(self):
        provider = PaymentFactory.get("paymee", {"api_key": "test"})
        assert isinstance(provider, PaymeeProvider)

    def test_get_stripe_provider(self):
        provider = PaymentFactory.get("stripe", {"webhook_secret": "test"})
        assert isinstance(provider, StripeProvider)

    def test_get_cash_provider(self):
        provider = PaymentFactory.get("cash", {})
        assert isinstance(provider, CashProvider)

    def test_get_unknown_provider_raises(self):
        with pytest.raises(HTTPException):
            PaymentFactory.get("nonexistent_provider", {})

    def test_get_provider_with_none_config(self):
        provider = PaymentFactory.get("cash", None)
        assert isinstance(provider, CashProvider)

    def test_get_provider_case_insensitive(self):
        provider = PaymentFactory.get("FLOUCI", {"webhook_secret": "test"})
        assert isinstance(provider, FlouciProvider)


@pytest.mark.payments
class TestBaseProviderDefaults:
    """Vérifie les méthodes par défaut de _BaseProvider."""

    @pytest.mark.asyncio
    async def test_refund_returns_manual_required(self):
        provider = CashProvider({})
        result = await provider.refund_payment("ref-123", amount=50.0)
        assert result["status"] == "manual_required"

    @pytest.mark.asyncio
    async def test_cancel_returns_manual_required(self):
        provider = CashProvider({})
        result = await provider.cancel_payment("ref-123")
        assert result["status"] == "manual_required"


import httpx


@pytest.mark.payments
class TestPaymentFactoryFlouciRuntimePaths:
    @pytest.mark.asyncio
    async def test_flouci_create_success_and_invalid_response(self):
        provider = FlouciProvider({"app_token": "t", "app_secret": "s"})
        ok = httpx.Response(200, request=httpx.Request("POST", "https://x"), json={"result": {"link": "https://pay", "payment_id": "p1"}})
        with patch("services.payment_factory._http_request_with_retry", new=AsyncMock(return_value=ok)):
            result = await provider.create_payment_link(12.5, reference="ref", success_url="ok", fail_url="ko")
        assert result["url"] == "https://pay" and result["id"] == "p1"
        bad = httpx.Response(200, request=httpx.Request("POST", "https://x"), json={})
        with patch("services.payment_factory._http_request_with_retry", new=AsyncMock(return_value=bad)):
            with pytest.raises(HTTPException, match="invalide"):
                await provider.create_payment_link(1)

    @pytest.mark.asyncio
    async def test_flouci_verify_status_mapping_and_http_error(self):
        provider = FlouciProvider({"app_token": "t", "app_secret": "s"})
        for raw, expected in (("SUCCESS", "paid"), ("DECLINED", "failed"), ("PENDING", "pending")):
            response = httpx.Response(200, request=httpx.Request("GET", "https://x"), json={"result": {"status": raw}})
            with patch("services.payment_factory._http_request_with_retry", new=AsyncMock(return_value=response)):
                assert (await provider.verify_payment("p"))["status"] == expected
        response = httpx.Response(503, request=httpx.Request("GET", "https://x"))
        with patch("services.payment_factory._http_request_with_retry", new=AsyncMock(return_value=response)):
            assert (await provider.verify_payment("p"))["status"] == "failed"

    @pytest.mark.asyncio
    async def test_http_retry_success_and_network_exhaustion(self):
        from services.payment_factory import _http_request_with_retry
        response = httpx.Response(200, request=httpx.Request("GET", "https://x"))
        client = AsyncMock()
        client.request = AsyncMock(side_effect=[httpx.NetworkError("temporary"), response])
        client.__aenter__.return_value = client
        with patch("services.payment_factory.httpx.AsyncClient", return_value=client), patch("services.payment_factory.asyncio.sleep", new=AsyncMock()):
            assert (await _http_request_with_retry("GET", "https://x", provider_name="test")).status_code == 200
        failing = AsyncMock()
        failing.request = AsyncMock(side_effect=httpx.NetworkError("down"))
        failing.__aenter__.return_value = failing
        with patch("services.payment_factory.httpx.AsyncClient", return_value=failing), patch("services.payment_factory.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(HTTPException) as exc:
                await _http_request_with_retry("GET", "https://x", provider_name="test")
            assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_konnect_create_payment_success_and_invalid_or_http_response():
    provider = KonnectProvider({"api_key": "key", "receiver_wallet_id": "wallet"})
    response = httpx.Response(200, request=httpx.Request("POST", "https://x"), json={"payUrl": "https://pay", "paymentRef": "ref"})
    with patch("services.payment_factory._http_request_with_retry", new=AsyncMock(return_value=response)) as request:
        result = await provider.create_payment_link(2.5, description="D", reference="R", customer_phone="216")
    assert result["url"] == "https://pay" and result["id"] == "ref"
    payload = request.await_args.kwargs["json_payload"]
    assert payload["amount"] == 2500 and payload["phoneNumber"] == "216"
    bad = httpx.Response(200, request=httpx.Request("POST", "https://x"), json={})
    with patch("services.payment_factory._http_request_with_retry", new=AsyncMock(return_value=bad)):
        with pytest.raises(HTTPException, match="Konnect"):
            await provider.create_payment_link(1)
    unavailable = KonnectProvider({})
    with pytest.raises(HTTPException, match="non configuré"):
        await unavailable.create_payment_link(1)


@pytest.mark.asyncio
async def test_konnect_verify_statuses_and_signature_fail_closed():
    provider = KonnectProvider({"api_key": "key"})
    for raw, expected in (("completed", "paid"), ("failed", "failed"), ("pending", "pending")):
        response = httpx.Response(200, request=httpx.Request("GET", "https://x"), json={"payment": {"status": raw}})
        with patch("services.payment_factory._http_request_with_retry", new=AsyncMock(return_value=response)):
            assert (await provider.verify_payment("r"))["status"] == expected
    assert provider.verify_webhook_signature(b"x", {})[0] is False
    signed = hmac.new(b"key", b"x", hashlib.sha256).hexdigest()
    assert provider.verify_webhook_signature(b"x", {"x-signature": signed})[0] is True
    assert provider.verify_webhook_signature(b"x", {"x-signature": "bad"})[1] == "invalid"
