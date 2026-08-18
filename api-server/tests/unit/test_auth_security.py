"""Tests unitaires pour middleware/auth.py — Dépendances d'authentification multi-tenant."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from middleware.auth import (
    _resolve_store_id,
    get_current_store,
    get_current_store_id,
    require_internal_health_rate_limit,
)
from middleware.tenant import current_tenant_id


@pytest.mark.unit
class TestResolveStoreId:
    """Vérifie _resolve_store_id()."""

    def test_resolves_from_context_var(self):
        token = current_tenant_id.set(42)
        assert _resolve_store_id() == 42
        current_tenant_id.reset(token)

    def test_resolves_from_request_state(self):
        current_tenant_id.set(None)
        request = MagicMock()
        request.state.store_id = 99
        assert _resolve_store_id(request) == 99

    def test_raises_when_no_context_and_no_request(self):
        current_tenant_id.set(None)
        with pytest.raises(HTTPException) as exc_info:
            _resolve_store_id(None)
        assert exc_info.value.status_code == 401

    def test_raises_when_no_context_and_no_store_in_request(self):
        current_tenant_id.set(None)
        request = MagicMock()
        request.state.store_id = None
        with pytest.raises(HTTPException) as exc_info:
            _resolve_store_id(request)
        assert exc_info.value.status_code == 401


@pytest.mark.unit
class TestGetCurrentStoreId:
    """Vérifie get_current_store_id()."""

    @pytest.mark.asyncio
    async def test_returns_store_id_from_request(self):
        token = current_tenant_id.set(55)
        request = MagicMock()
        request.state.store_id = 55
        result = await get_current_store_id(request)
        assert result == 55
        current_tenant_id.reset(token)


@pytest.mark.unit
class TestGetCurrentStore:
    """Vérifie get_current_store()."""

    @pytest.mark.asyncio
    async def test_returns_store_when_found(self):
        mock_store = MagicMock()
        mock_store.id = 1
        mock_store.name = "Test Store"
        mock_db = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_store)
        mock_db.execute = AsyncMock(return_value=mock_result)
        request = MagicMock()
        request.state.store_id = 1

        store = await get_current_store(request, db=mock_db)
        assert store.id == 1

    @pytest.mark.asyncio
    async def test_raises_404_when_store_not_found(self):
        mock_db = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)
        request = MagicMock()
        request.state.store_id = 999

        with pytest.raises(HTTPException) as exc_info:
            await get_current_store(request, db=mock_db)
        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestRequireInternalHealthToken:
    """Vérifie require_internal_health_token()."""

    @pytest.mark.asyncio
    async def test_valid_token_passes(self):
        from middleware.auth import require_internal_health_token
        with patch("middleware.auth.hmac.compare_digest", return_value=True):
            # Should not raise
            await require_internal_health_token(x_internal_token="valid-token")

    @pytest.mark.asyncio
    async def test_invalid_token_raises_403(self):
        from middleware.auth import require_internal_health_token
        with patch("middleware.auth.hmac.compare_digest", return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                await require_internal_health_token(x_internal_token="wrong-token")
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_token_raises_403(self):
        from middleware.auth import require_internal_health_token
        with pytest.raises(HTTPException) as exc_info:
            await require_internal_health_token(x_internal_token=None)
        assert exc_info.value.status_code == 403


@pytest.mark.unit
class TestRequireInternalHealthRateLimit:
    """Vérifie require_internal_health_rate_limit()."""

    def setup_method(self):
        from middleware.auth import _HEALTH_DETAIL_BUCKET
        _HEALTH_DETAIL_BUCKET.clear()

    def teardown_method(self):
        from middleware.auth import _HEALTH_DETAIL_BUCKET
        _HEALTH_DETAIL_BUCKET.clear()

    @pytest.mark.asyncio
    async def test_first_request_passes(self):
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.url = MagicMock()
        request.url.path = "/api/v1/ops/health/detailed"
        # Should not raise
        await require_internal_health_rate_limit(request)

    @pytest.mark.asyncio
    async def test_rate_limited_request_raises_429(self):
        from middleware.auth import _HEALTH_DETAIL_BUCKET
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.url = MagicMock()
        request.url.path = "/api/v1/ops/health/detailed"
        # First call creates the bucket (sets expiry 10s in future)
        await require_internal_health_rate_limit(request)
        # Second call within the 10s window should raise 429
        with pytest.raises(HTTPException) as exc_info:
            await require_internal_health_rate_limit(request)
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_expired_bucket_allows_request(self):
        from middleware.auth import _HEALTH_DETAIL_BUCKET
        bucket_key = "127.0.0.1:/api/v1/ops/health/detailed"
        _HEALTH_DETAIL_BUCKET[bucket_key] = time.monotonic() - 1.0  # expired
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.url = MagicMock()
        request.url.path = "/api/v1/ops/health/detailed"
        # Should not raise — bucket expired
        await require_internal_health_rate_limit(request)

    @pytest.mark.asyncio
    async def test_different_clients_not_rate_limited_together(self):
        from middleware.auth import _HEALTH_DETAIL_BUCKET
        bucket_key_a = "127.0.0.1:/api/v1/ops/health/detailed"
        _HEALTH_DETAIL_BUCKET[bucket_key_a] = time.monotonic() + 10.0
        request_b = MagicMock()
        request_b.client = MagicMock()
        request_b.client.host = "10.0.0.1"
        request_b.url = MagicMock()
        request_b.url.path = "/api/v1/ops/health/detailed"
        # Client B should not be rate limited
        await require_internal_health_rate_limit(request_b)
