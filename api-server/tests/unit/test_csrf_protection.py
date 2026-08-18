"""Tests unitaires pour middleware/csrf_protection.py."""
from __future__ import annotations

import hashlib
import hmac as hmac_module
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from middleware.csrf_protection import (
    CSRF_COOKIE_NAME,
    CSRF_EXEMPT_PATHS,
    CSRF_HEADER_NAME,
    CSRF_TOKEN_MAX_AGE,
    SAFE_METHODS,
    CSRFProtectionMiddleware,
    _generate_csrf_token,
    _verify_csrf_token,
)


@pytest.mark.unit
class TestGenerateCsrfToken:
    """Vérifie _generate_csrf_token()."""

    def test_token_format_has_four_parts(self):
        token = _generate_csrf_token(session_id="test-session")
        parts = token.split(".")
        assert len(parts) == 4

    def test_token_has_timestamp(self):
        token = _generate_csrf_token()
        timestamp = int(token.split(".")[0])
        assert abs(time.time() - timestamp) < 5

    def test_token_has_random_part(self):
        token1 = _generate_csrf_token()
        token2 = _generate_csrf_token()
        # Le random_part (index 1) doit différer
        assert token1.split(".")[1] != token2.split(".")[1]

    def test_token_has_session_included(self):
        token = _generate_csrf_token(session_id="unique-session-123")
        parts = token.split(".")
        assert "unique-session-123" in parts[2]


@pytest.mark.unit
class TestVerifyCsrfToken:
    """Vérifie _verify_csrf_token()."""

    def test_valid_token_passes(self):
        token = _generate_csrf_token()
        assert _verify_csrf_token(token) is True

    def test_empty_token_fails(self):
        assert _verify_csrf_token("") is False

    def test_none_token_fails(self):
        assert _verify_csrf_token(None) is False

    def test_wrong_format_fails(self):
        assert _verify_csrf_token("only-one-part") is False

    def test_tampered_token_fails(self):
        token = _generate_csrf_token()
        parts = token.split(".")
        parts[-1] = "tampered-signature"
        tampered = ".".join(parts)
        assert _verify_csrf_token(tampered) is False

    def test_expired_token_fails(self):
        # Génère un token avec un timestamp expiré
        # Il faut recalculer la signature
        with patch("middleware.csrf_protection._CSRF_SECRET", "test-secret"):
            payload_for_sig = f"{int(time.time()) - CSRF_TOKEN_MAX_AGE - 100}.abcd1234.session"
            sig = hmac_module.new(
                b"test-secret", payload_for_sig.encode(), hashlib.sha256
            ).hexdigest()
            expired_token = f"{payload_for_sig}.{sig}"
            assert _verify_csrf_token(expired_token) is False

    def test_fresh_token_passes(self):
        token = _generate_csrf_token()
        assert _verify_csrf_token(token) is True


@pytest.mark.unit
class TestCsrfExemptPaths:
    """Vérifie les chemins exemptés de CSRF."""

    def test_login_exempt(self):
        assert "/api/v1/auth/login" in CSRF_EXEMPT_PATHS

    def test_register_exempt(self):
        assert "/api/v1/auth/register" in CSRF_EXEMPT_PATHS

    def test_health_exempt(self):
        assert "/health" in CSRF_EXEMPT_PATHS

    def test_metrics_exempt(self):
        assert "/metrics" in CSRF_EXEMPT_PATHS

    def test_docs_exempt(self):
        assert "/docs" in CSRF_EXEMPT_PATHS

    def test_webhooks_exempt(self):
        assert "/api/v1/whatsapp/webhook" in CSRF_EXEMPT_PATHS
        assert "/api/v1/payments/webhook" in CSRF_EXEMPT_PATHS

    def test_forgot_password_exempt(self):
        assert "/api/v1/auth/forgot-password" in CSRF_EXEMPT_PATHS

    def test_reset_password_exempt(self):
        assert "/api/v1/auth/reset-password" in CSRF_EXEMPT_PATHS

    def test_billing_webhook_exempt(self):
        assert "/api/v1/billing/webhook/" in CSRF_EXEMPT_PATHS


@pytest.mark.unit
class TestSafeMethods:
    """Vérifie les méthodes safe pour CSRF."""

    def test_get_is_safe(self):
        assert "GET" in SAFE_METHODS

    def test_head_is_safe(self):
        assert "HEAD" in SAFE_METHODS

    def test_options_is_safe(self):
        assert "OPTIONS" in SAFE_METHODS

    def test_post_is_not_safe(self):
        assert "POST" not in SAFE_METHODS

    def test_put_is_not_safe(self):
        assert "PUT" not in SAFE_METHODS

    def test_delete_is_not_safe(self):
        assert "DELETE" not in SAFE_METHODS


@pytest.mark.unit
class TestCsrfConstants:
    """Vérifie les constantes."""

    def test_cookie_name(self):
        assert CSRF_COOKIE_NAME == "csrf_token"

    def test_header_name(self):
        assert CSRF_HEADER_NAME == "X-CSRF-Token"

    def test_token_max_age_is_one_hour(self):
        assert CSRF_TOKEN_MAX_AGE == 3600
