"""Tests unitaires pour middleware/tenant.py — couverture des chemins JWT, MFA, kill-switch."""
from __future__ import annotations

import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from starlette.datastructures import URL, Headers

from middleware.tenant import (
    MFA_EXEMPT_PATHS,
    PUBLIC_EXACT,
    PUBLIC_PREFIXES,
    TenantMiddleware,
    _is_public,
    current_tenant_id,
    current_user_role,
)


@pytest.mark.unit
class TestIsPublic:
    """Vérifie _is_public() pour chaque catégorie de chemins."""

    def test_health_paths_are_public(self):
        assert _is_public("/health") is True
        assert _is_public("/health/") is True
        assert _is_public("/health/db") is True
        assert _is_public("/api/health") is True
        assert _is_public("/api/v1/health") is True
        assert _is_public("/api/v1/health/detailed") is True

    def test_docs_paths_are_public(self):
        assert _is_public("/docs") is True
        assert _is_public("/redoc") is True
        assert _is_public("/openapi.json") is True

    def test_metrics_paths_are_public(self):
        assert _is_public("/metrics") is True
        assert _is_public("/metrics/") is True

    def test_auth_paths_are_public(self):
        assert _is_public("/api/v1/auth/login") is True
        assert _is_public("/api/v1/auth/register") is True
        assert _is_public("/api/v1/auth/refresh") is True
        assert _is_public("/api/v1/auth/logout") is True
        assert _is_public("/api/v1/auth/forgot-password") is True
        assert _is_public("/api/v1/auth/reset-password") is True
        assert _is_public("/api/v1/auth/mfa/verify") is True
        assert _is_public("/api/v1/auth/mfa/setup") is True

    def test_webhook_prefixes_are_public(self):
        assert _is_public("/api/v1/whatsapp/webhook") is True
        assert _is_public("/api/v1/payments/webhook") is True
        assert _is_public("/api/v1/social/instagram/webhook") is True
        assert _is_public("/api/v1/social/facebook/webhook") is True
        assert _is_public("/api/v1/social/tiktok/webhook") is True

    def test_storefront_is_public(self):
        assert _is_public("/api/v1/storefront/products") is True
        assert _is_public("/api/v1/products/public") is True

    def test_non_public_path(self):
        assert _is_public("/api/v1/stores") is False
        assert _is_public("/api/v1/orders") is False
        assert _is_public("/api/v1/products") is False

    def test_gdpr_retention_policy_public(self):
        assert _is_public("/api/v1/settings/gdpr/retention-policy") is True

    def test_billing_plans_public(self):
        assert _is_public("/api/v1/billing/plans") is True


@pytest.mark.unit
class TestTenantMiddlewareDispatch:
    """Vérifie les branches principales du dispatch du TenantMiddleware."""

    @pytest.mark.asyncio
    async def test_public_path_bypasses_jwt(self):
        """Un chemin public passe sans token JWT."""
        middleware = TenantMiddleware(app=None)
        call_next = AsyncMock(return_value=MagicMock())
        scope = {
            "type": "http",
            "method": "GET",
            "headers": [],
            "query_string": b"",
            "path": "/health",
        }
        request = Request(scope)
        _ = await middleware.dispatch(request, call_next)
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self):
        """Sans token, retourne 401."""
        with patch.dict(os.environ, {"ENV": "test"}):
            middleware = TenantMiddleware(app=None)
            call_next = AsyncMock()
            scope = {
                "type": "http",
                "method": "GET",
                "headers": [],
                "query_string": b"",
                "path": "/api/v1/stores",
            }
            request = Request(scope)
            response = await middleware.dispatch(request, call_next)
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_health_header_bypasses_jwt(self):
        """X-Internal-Token valide bypass le middleware JWT."""
        middleware = TenantMiddleware(app=None)
        call_next = AsyncMock(return_value=MagicMock())
        with patch("middleware.tenant.settings") as mock_settings:
            mock_settings.INTERNAL_HEALTH_TOKEN = "valid-internal-token"
            # /api/v1/ops/ is in CSRF_EXEMPT but NOT in PUBLIC paths
            # The middleware checks internal token after checking public
            # So we need a non-public path that will reach the internal token check
            scope = {
                "type": "http",
                "method": "GET",
                "headers": [(b"x-internal-token", b"valid-internal-token")],
                "query_string": b"",
                "path": "/api/v1/ops/credits/stats/monthly",
            }
            request = Request(scope)
            _ = await middleware.dispatch(request, call_next)
            call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_jwt_returns_401(self):
        """JWT invalide retourne 401."""
        from jwt.exceptions import PyJWTError
        with patch("middleware.tenant.settings") as mock_settings:
            mock_settings.decode_jwt = MagicMock(side_effect=PyJWTError("invalid"))
            mock_settings.INTERNAL_HEALTH_TOKEN = ""
            middleware = TenantMiddleware(app=None)
            call_next = AsyncMock()
            scope = {
                "type": "http",
                "method": "GET",
                "headers": [("authorization", "Bearer invalid-token")],
                "query_string": b"",
                "path": "/api/v1/stores",
            }
            request = Request(scope)
            response = await middleware.dispatch(request, call_next)
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_mfa_required_without_verification_returns_401(self):
        """Token avec mfa_required=True et mfa_verified=False bloque l'accès."""
        token_payload = {
            "store_id": 1,
            "role": "owner",
            "mfa_required": True,
            "mfa_verified": False,
            "user_id": 42,
        }
        middleware = TenantMiddleware(app=None)
        call_next = AsyncMock()
        with patch("middleware.tenant.settings") as mock_settings:
            mock_settings.decode_jwt = MagicMock(return_value=token_payload)
            mock_settings.INTERNAL_HEALTH_TOKEN = ""
            scope = {
                "type": "http",
                "method": "GET",
                "headers": [(b"authorization", b"Bearer fake-token")],
                "query_string": b"",
                "path": "/api/v1/stores",
            }
            request = Request(scope)
            response = await middleware.dispatch(request, call_next)
            assert response.status_code == 401
            body = json.loads(response.body)
            assert "mfa_verification_required" in body["error"]

    @pytest.mark.asyncio
    async def test_mfa_exempt_paths_allow_access(self):
        """Les chemins MFA_EXEMPT_PATHS passent même si mfa_required."""
        token_payload = {
            "store_id": 1,
            "role": "owner",
            "mfa_required": True,
            "mfa_verified": False,
            "user_id": 42,
        }
        with patch("middleware.tenant.settings") as mock_settings:
            mock_settings.decode_jwt = MagicMock(return_value=token_payload)
            mock_settings.INTERNAL_HEALTH_TOKEN = ""
            middleware = TenantMiddleware(app=None)
            call_next = AsyncMock(return_value=MagicMock())
            for path in ["/api/v1/auth/mfa/verify", "/api/v1/auth/mfa/setup"]:
                call_next.reset_mock()
                scope = {
                    "type": "http",
                    "method": "GET",
                    "headers": [("authorization", "Bearer fake-token")],
                    "query_string": b"",
                    "path": path,
                }
                request = Request(scope)
                _ = await middleware.dispatch(request, call_next)
                call_next.assert_called_once()


@pytest.mark.unit
class TestMFAExemptPaths:
    """Vérifie que tous les chemins MFA exemptés sont bien définis."""

    def test_mfa_verify_is_exempt(self):
        assert "/api/v1/auth/mfa/verify" in MFA_EXEMPT_PATHS

    def test_mfa_setup_is_exempt(self):
        assert "/api/v1/auth/mfa/setup" in MFA_EXEMPT_PATHS

    def test_logout_is_exempt(self):
        assert "/api/v1/auth/logout" in MFA_EXEMPT_PATHS

    def test_byok_status_is_exempt(self):
        assert "/api/v1/billing/byok-status" in MFA_EXEMPT_PATHS


@pytest.mark.unit
class TestPublicExactCoverage:
    """Vérifie que PUBLIC_EXACT couvre tous les cas attendus."""

    def test_health_variants(self):
        for suffix in ["", "/", "/db", "/redis", "/detailed"]:
            assert f"/api/v1/health{suffix}" in PUBLIC_EXACT

    def test_auth_endpoints(self):
        assert "/api/v1/auth/login" in PUBLIC_EXACT
        assert "/api/v1/auth/register" in PUBLIC_EXACT
        assert "/api/v1/auth/refresh" in PUBLIC_EXACT
        assert "/api/v1/auth/logout" in PUBLIC_EXACT
        assert "/api/v1/auth/forgot-password" in PUBLIC_EXACT
        assert "/api/v1/auth/reset-password" in PUBLIC_EXACT


@pytest.mark.unit
class TestContextVars:
    """Vérifie que les ContextVars sont correctement initialisés."""

    def test_tenant_id_default_none(self):
        assert current_tenant_id.get() is None

    def test_user_role_default_none(self):
        assert current_user_role.get() is None

    def test_set_and_get_tenant_id(self):
        token = current_tenant_id.set(42)
        assert current_tenant_id.get() == 42
        current_tenant_id.reset(token)
        assert current_tenant_id.get() is None
