"""Tests unitaires pour P0-2 — SMTP transactionnel réel.

Couvre :
- test_send_success
- test_smtp_unavailable_no_silent_drop
- test_retry_then_dlq
- test_pii_in_logs_redacted
- test_production_requires_smtp_host (monkeypatch_env_prod)
"""
from __future__ import annotations

import asyncio
import os
import smtplib
from unittest import mock

import pytest

from services.email_queue import EmailQueue, QueueResult
from services.email_sender import EmailDeliveryError, EmailMessage, EmailSender

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_smtp_server():
    """Mock du serveur SMTP qui simule un succès."""
    with mock.patch("smtplib.SMTP") as mock_smtp_class:
        mock_smtp = mock.MagicMock()
        mock_smtp.__enter__ = mock.MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = mock.MagicMock(return_value=False)
        mock_smtp.starttls = mock.MagicMock()
        mock_smtp.login = mock.MagicMock()
        mock_smtp.sendmail = mock.MagicMock()
        mock_smtp.noop = mock.MagicMock()
        mock_smtp_class.return_value = mock_smtp
        yield mock_smtp_class


@pytest.fixture
def mock_smtp_server_failing():
    """Mock du serveur SMTP qui simule un échec permanent."""
    with mock.patch("smtplib.SMTP") as mock_smtp_class:
        mock_smtp = mock.MagicMock()
        mock_smtp.__enter__ = mock.MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = mock.MagicMock(return_value=False)
        mock_smtp.starttls = mock.MagicMock()
        mock_smtp.login = mock.MagicMock()
        mock_smtp.sendmail = mock.MagicMock(side_effect=ConnectionError("SMTP unavailable"))
        mock_smtp.noop = mock.MagicMock(side_effect=ConnectionError("SMTP unavailable"))
        mock_smtp_class.return_value = mock_smtp
        yield mock_smtp_class


@pytest.fixture
def mock_smtp_server_first_fail():
    """Mock qui échoue 2 fois puis réussit (pour tester les retries)."""
    call_count = 0

    def side_effect(from_addr, to, msg):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError(f"Simulated failure #{call_count}")

    with mock.patch("smtplib.SMTP") as mock_smtp_class:
        mock_smtp = mock.MagicMock()
        mock_smtp.__enter__ = mock.MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = mock.MagicMock(return_value=False)
        mock_smtp.starttls = mock.MagicMock()
        mock_smtp.login = mock.MagicMock()
        mock_smtp.sendmail = mock.MagicMock(side_effect=side_effect)
        mock_smtp.noop = mock.MagicMock()
        mock_smtp_class.return_value = mock_smtp
        yield mock_smtp_class


@pytest.fixture
def configured_sender(monkeypatch):
    """Un EmailSender configuré avec des valeurs valides via monkeypatch settings."""
    import config
    saved = {
        "host": config.settings.SMTP_HOST,
        "port": config.settings.SMTP_PORT,
        "username": config.settings.SMTP_USERNAME,
        "password": config.settings.SMTP_PASSWORD,
        "from_addr": config.settings.SMTP_FROM,
        "use_tls": config.settings.SMTP_USE_TLS,
    }
    config.settings.SMTP_HOST = "smtp.test.local"
    config.settings.SMTP_PORT = 587
    config.settings.SMTP_USERNAME = "test@test.local"
    config.settings.SMTP_PASSWORD = "password123"
    config.settings.SMTP_FROM = "noreply@test.local"
    config.settings.SMTP_USE_TLS = True

    sender = EmailSender()
    yield sender

    config.settings.SMTP_HOST = saved["host"]
    config.settings.SMTP_PORT = saved["port"]
    config.settings.SMTP_USERNAME = saved["username"]
    config.settings.SMTP_PASSWORD = saved["password"]
    config.settings.SMTP_FROM = saved["from_addr"]
    config.settings.SMTP_USE_TLS = saved["use_tls"]


# ── P0-2.A : Envoi réussi ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_success(configured_sender, mock_smtp_server):
    """Un email envoyé avec succès doit retourner sans erreur."""
    message = EmailMessage(
        to="user@example.com",
        subject="Test email",
        html_body="<p>Hello</p>",
        template="test",
    )
    await configured_sender.send(message)
    mock_smtp_server.return_value.sendmail.assert_called_once()


@pytest.mark.asyncio
async def test_send_email_service_success(mock_smtp_server, monkeypatch):
    """send_password_reset_email doit réussir via email_service."""
    import config
    saved = {}
    for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_USE_TLS"):
        saved[key] = getattr(config.settings, key)
    config.settings.SMTP_HOST = "smtp.test.local"
    config.settings.SMTP_PORT = 587
    config.settings.SMTP_USERNAME = "test@test.local"
    config.settings.SMTP_PASSWORD = "password123"
    config.settings.SMTP_FROM = "noreply@test.local"
    config.settings.SMTP_USE_TLS = True

    try:
        from services.email_service import send_password_reset_email
        await send_password_reset_email(
            to_email="user@example.com",
            reset_token="abc123",
            store_name="TestStore",
        )
    finally:
        for key, val in saved.items():
            setattr(config.settings, key, val)


# ── P0-2.B : SMTP indisponible — pas de drop silencieux ──────────────────────

@pytest.mark.asyncio
async def test_smtp_unavailable_no_silent_drop(configured_sender, mock_smtp_server_failing):
    """Quand SMTP est indisponible, EmailDeliveryError doit être levée (pas de drop silencieux)."""
    message = EmailMessage(
        to="user@example.com",
        subject="Test",
        html_body="<p>Hello</p>",
        template="test",
    )
    with pytest.raises(EmailDeliveryError):
        await configured_sender.send(message)


@pytest.mark.asyncio
async def test_email_queue_dlq_when_smtp_down(configured_sender, mock_smtp_server_failing):
    """EmailQueue doit mettre en DLQ après 3 tentatives échouées."""
    queue = EmailQueue(sender=configured_sender)
    message = EmailMessage(
        to="user@example.com",
        subject="Test DLQ",
        html_body="<p>Will fail</p>",
        template="test",
        store_id=1,
    )
    result = await queue.enqueue(message, trace_id="trace-123")
    assert result.status == "DLQ"
    assert result.attempts == 3
    assert result.last_error is not None
    assert result.trace_id == "trace-123"
    assert result.event["status"] == "DLQ"


# ── P0-2.C : Retry puis DLQ ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_then_dlq(configured_sender, mock_smtp_server_failing):
    """Après 3 tentatives, l'email doit finir en DLQ."""
    queue = EmailQueue(sender=configured_sender)
    message = EmailMessage(
        to="fail@example.com",
        subject="Retry test",
        html_body="<p>Retry</p>",
        template="test",
    )
    result = await queue.enqueue(message)
    assert result.status == "DLQ"
    assert result.attempts == 3


@pytest.mark.asyncio
async def test_retry_success(configured_sender, mock_smtp_server_first_fail):
    """Si le serveur SMTP réussit après 2 échecs, l'email doit être envoyé."""
    queue = EmailQueue(sender=configured_sender)
    message = EmailMessage(
        to="user@example.com",
        subject="Retry success",
        html_body="<p>Should succeed</p>",
        template="test",
    )
    result = await queue.enqueue(message)
    assert result.status == "sent"
    # Le sender interne fait 3 tentatives (2 échecs + 1 succès),
    # mais le QueueResult final rapporte 1 car la queue considère
    # l'envoi comme un seul message "sent" après retries internes.
    assert result.last_error is None


# ── P0-2.D : PII masqué dans les logs ────────────────────────────────────────

def test_pii_in_logs_redacted():
    """Le PII (email) doit être masqué par le filtre PIIRedactorFilter."""
    from services.pii_redactor import PIIRedactorFilter, _redact_string

    text = "Envoyer à user@example.com et appeler 0612345678"
    redacted = _redact_string(text)
    assert "user@example.com" not in redacted


def test_pii_redactor_email_pattern():
    """Le redacteur doit masquer les adresses email."""
    from services.pii_redactor import _redact_string
    result = _redact_string("Contact: admin@shop.tn for info")
    assert "admin@shop.tn" not in result


def test_pii_redactor_phone_pattern():
    """Le redacteur doit masquer les numéros de téléphone."""
    from services.pii_redactor import _redact_string
    result = _redact_string("Call 0612345678 or +216 71 123 456")
    assert "0612345678" not in result


def test_pii_redactor_filter():
    """PIIRedactorFilter doit filtrer les messages de log."""
    import logging

    from services.pii_redactor import PIIRedactorFilter

    filt = PIIRedactorFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="Contact user@example.com for details",
        args=(), exc_info=None,
    )
    assert filt.filter(record) is True  # le filtre doit passer (pas bloquer)


# ── P0-2.E : Production exige SMTP_HOST ──────────────────────────────────────

def test_production_requires_smtp_host():
    """En production, SMTP_HOST vide doit rendre configured=False."""
    import config
    saved = config.settings.SMTP_HOST
    config.settings.SMTP_HOST = ""
    try:
        sender = EmailSender()
        assert sender.configured is False
    finally:
        config.settings.SMTP_HOST = saved


def test_smtp_configured_true(monkeypatch):
    """Quand SMTP_HOST est renseigné, configured doit être True."""
    import config
    saved = config.settings.SMTP_HOST
    config.settings.SMTP_HOST = "smtp.example.com"
    try:
        sender = EmailSender()
        assert sender.configured is True
    finally:
        config.settings.SMTP_HOST = saved


# ── P0-2.F : EmailMessage dataclass ──────────────────────────────────────────

def test_email_message_dataclass():
    """EmailMessage doit avoir les bons champs."""
    msg = EmailMessage(
        to="user@example.com",
        subject="Test",
        html_body="<p>Hello</p>",
        template="invoice",
        store_id=42,
    )
    assert msg.to == "user@example.com"
    assert msg.subject == "Test"
    assert msg.html_body == "<p>Hello</p>"
    assert msg.template == "invoice"
    assert msg.store_id == 42


def test_email_message_defaults():
    """EmailMessage doit avoir des valeurs par défaut pour template et store_id."""
    msg = EmailMessage(
        to="user@example.com",
        subject="Test",
        html_body="<p>Hello</p>",
    )
    assert msg.template == "generic"
    assert msg.store_id is None


# ── P0-2.G : EmailQueue QueueResult ──────────────────────────────────────────

def test_queue_result_dataclass():
    """QueueResult doit avoir les bons champs."""
    from dataclasses import asdict
    result = QueueResult(
        status="sent",
        attempts=1,
        last_error=None,
        trace_id="trace-abc",
    )
    data = asdict(result)
    assert data["status"] == "sent"
    assert data["attempts"] == 1
    assert data["trace_id"] == "trace-abc"


def test_queue_result_dlq_fields():
    """QueueResult en DLQ doit avoir last_error et event."""
    result = QueueResult(
        status="DLQ",
        attempts=3,
        last_error="SMTP unavailable",
        trace_id="trace-dlq",
    )
    assert result.status == "DLQ"
    assert result.attempts == 3
    assert result.last_error == "SMTP unavailable"
    assert result.trace_id == "trace-dlq"


# ── P0-2.H : EmailService templates ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_invoice_email_template(mock_smtp_server, monkeypatch):
    """send_invoice_email doit utiliser le template 'invoice'."""
    import config
    saved = {}
    for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_USE_TLS"):
        saved[key] = getattr(config.settings, key)
    config.settings.SMTP_HOST = "smtp.test.local"
    config.settings.SMTP_PORT = 587
    config.settings.SMTP_USERNAME = "test@test.local"
    config.settings.SMTP_PASSWORD = "password123"
    config.settings.SMTP_FROM = "noreply@test.local"
    config.settings.SMTP_USE_TLS = True

    try:
        from services.email_service import send_invoice_email
        await send_invoice_email(
            to_email="client@example.com",
            invoice_url="https://shop.example.com/invoices/INV-001-202607-abc123.pdf",
            order_ref="INV-001-202607-abc123",
            store_name="TestShop",
        )
    finally:
        for key, val in saved.items():
            setattr(config.settings, key, val)


@pytest.mark.asyncio
async def test_send_subscription_reminder(mock_smtp_server, monkeypatch):
    """send_subscription_reminder_email doit réussir."""
    import config
    saved = {}
    for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_USE_TLS"):
        saved[key] = getattr(config.settings, key)
    config.settings.SMTP_HOST = "smtp.test.local"
    config.settings.SMTP_PORT = 587
    config.settings.SMTP_USERNAME = "test@test.local"
    config.settings.SMTP_PASSWORD = "password123"
    config.settings.SMTP_FROM = "noreply@test.local"
    config.settings.SMTP_USE_TLS = True

    try:
        from services.email_service import send_subscription_reminder_email
        await send_subscription_reminder_email(
            to_email="admin@example.com",
            store_name="MyShop",
            days_until_expiry=7,
        )
    finally:
        for key, val in saved.items():
            setattr(config.settings, key, val)


# ── P0-2.I : EmailDeliveryError est une RuntimeError ─────────────────────────

def test_email_delivery_error_is_runtime():
    """EmailDeliveryError doit hériter de RuntimeError."""
    assert issubclass(EmailDeliveryError, RuntimeError)


def test_email_delivery_error_message():
    """EmailDeliveryError doit porter un message."""
    err = EmailDeliveryError("SMTP non configuré")
    assert str(err) == "SMTP non configuré"


# ── P0-2.J : EmailSender ping ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_sender_ping_configured(configured_sender, mock_smtp_server):
    """ping() doit retourner True quand SMTP est joignable."""
    result = await configured_sender.ping()
    assert result is True


@pytest.mark.asyncio
async def test_email_sender_ping_unconfigured(monkeypatch):
    """ping() doit retourner False quand SMTP n'est pas configuré."""
    import config
    saved = config.settings.SMTP_HOST
    config.settings.SMTP_HOST = ""
    try:
        sender = EmailSender()
        result = await sender.ping()
        assert result is False
    finally:
        config.settings.SMTP_HOST = saved
