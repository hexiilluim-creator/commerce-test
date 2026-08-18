"""Couverture comportementale des petits services de sécurité et résilience."""
import logging
from types import SimpleNamespace

import pytest

from services import circuit_breaker as cb
from services.payment_link_ai_tool import generate_payment_link_for_ai
from services.pii_redactor import PIIRedactorFilter, _redact_recursive, _redact_string
from services.ssrf_guard import SSRFBlocked, assert_safe_external_url


def test_ssrf_rejects_invalid_schemes_hosts_and_private_addresses(monkeypatch):
    for url in ("file:///etc/passwd", "https:///missing", "http://localhost/x"):
        with pytest.raises(SSRFBlocked):
            assert_safe_external_url(url)

    monkeypatch.setattr("services.ssrf_guard.socket.getaddrinfo", lambda *a: [(2, 0, 0, "", ("10.0.0.4", 0))])
    with pytest.raises(SSRFBlocked, match="interne/réservée"):
        assert_safe_external_url("https://example.test/resource")


def test_ssrf_allows_public_ip_and_rejects_dns_failure(monkeypatch):
    monkeypatch.setattr("services.ssrf_guard.socket.getaddrinfo", lambda *a: [(2, 0, 0, "", ("93.184.216.34", 443))])
    assert_safe_external_url("https://example.test/resource")

    import socket
    def fail(*args):
        raise socket.gaierror("offline")
    monkeypatch.setattr("services.ssrf_guard.socket.getaddrinfo", fail)
    with pytest.raises(SSRFBlocked, match="Résolution DNS impossible"):
        assert_safe_external_url("https://unknown.test")


def test_pii_redactor_masks_card_email_phone_cin_and_nested_data():
    text = _redact_string("mail x@example.com card 4111 1111 1111 1111 phone +21622123456 cin 12345678")
    assert "x@example.com" not in text and "4111" not in text and "12345678" not in text
    nested = _redact_recursive({"a": ["x@example.com"], "b": ("4111 1111 1111 1111",), "n": 7})
    assert nested["a"][0] == "[EMAIL]"
    assert nested["b"][0] == "[CARD]"
    assert nested["n"] == 7


def test_pii_filter_redacts_message_and_tuple_args():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "email %s", ("x@example.com",), None)
    assert PIIRedactorFilter().filter(record) is True
    assert record.msg == "email %s"
    assert record.args == ("[EMAIL]",)


@pytest.mark.asyncio
async def test_circuit_breaker_opens_blocks_recovers_and_reports(monkeypatch):
    breaker = cb.CircuitBreaker("unit", failure_threshold=2, recovery_timeout=10)
    assert breaker.state == "closed"
    assert breaker.is_open is False
    await breaker.record_failure()
    await breaker.record_failure()
    assert breaker.state == "open"
    assert breaker.is_open is True
    await breaker.record_success()
    assert breaker.state == "closed"
    assert breaker.stats()["name"] == "unit"


def test_circuit_breaker_registry_creates_and_lists():
    breaker = cb.get_breaker("unit-registry")
    assert cb.get_breaker("unit-registry") is breaker
    assert any(item["name"] == "unit-registry" for item in cb.list_breakers())


@pytest.mark.asyncio
async def test_payment_link_ai_returns_configuration_error():
    result = await generate_payment_link_for_ai(None, SimpleNamespace(payment_config=None, onboarding_completed=True), None, 10, "x")
    assert result == {"success": False, "url": None, "invoice_number": None, "error": "Store payment not configured"}


@pytest.mark.asyncio
async def test_payment_link_ai_persists_and_returns_url(monkeypatch):
    class FakeDB:
        def __init__(self): self.added = None
        def add(self, item): self.added = item
        async def flush(self): self.added.id = 42
    db = FakeDB()
    store = SimpleNamespace(id=9, payment_config={"provider": "paymee"}, onboarding_completed=True)
    customer = SimpleNamespace(id=7)
    result = await generate_payment_link_for_ai(db, store, customer, 25.5, "part", order_id=3, channel="whatsapp")
    assert result["success"] is True
    assert result["payment_link_id"] == 42
    assert result["url"].endswith(f"/api/v1/storefront/pay/{db.added.token}")
    assert db.added.invoice_number.startswith("INV-9-")
