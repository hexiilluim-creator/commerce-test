"""tests/test_audit_log.py — Couverture middleware/audit_log.py.

Couvre :
  - _should_audit (paths audités, méthodes write, statuts sécurité)
  - _mask_sensitive (Authorization masqué, headers normaux conservés)
  - _sign_entry (HMAC déterministe, tamper-proof)
  - AuditLogMiddleware dispatch (log sur POST, pas de log GET /api/v1/products)
  - Vérification HMAC offline
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")

from middleware.audit_log import (  # noqa: E402
    AuditLogMiddleware,
    _mask_sensitive,
    _should_audit,
    _sign_entry,
)

pytestmark = pytest.mark.unit


# ─── Tests _should_audit ──────────────────────────────────────────────────────

def test_should_audit_auth_path():
    assert _should_audit("/api/v1/auth/login", "POST", 200) is True


def test_should_audit_admin_path():
    assert _should_audit("/api/v1/admin/users", "GET", 200) is True


def test_should_audit_billing_path():
    assert _should_audit("/api/v1/billing/subscribe", "POST", 200) is True


def test_should_audit_401_status():
    assert _should_audit("/api/v1/products", "GET", 401) is True


def test_should_audit_403_status():
    assert _should_audit("/api/v1/products", "GET", 403) is True


def test_should_audit_429_status():
    assert _should_audit("/api/v1/products", "GET", 429) is True


def test_should_audit_write_method():
    assert _should_audit("/api/v1/products", "POST", 201) is True


def test_should_not_audit_get_non_sensitive():
    assert _should_audit("/api/v1/products", "GET", 200) is False


def test_should_audit_delete_method():
    assert _should_audit("/api/v1/products/1", "DELETE", 200) is True


def test_should_audit_patch_method():
    assert _should_audit("/api/v1/orders/5", "PATCH", 200) is True


# ─── Tests _mask_sensitive ────────────────────────────────────────────────────

def test_mask_authorization_header():
    headers = {"authorization": "Bearer eyJhbGci...", "content-type": "application/json"}
    masked = _mask_sensitive(headers)
    assert masked["authorization"] == "***REDACTED***"
    assert masked["content-type"] == "application/json"


def test_mask_cookie_header():
    headers = {"cookie": "session=abc123", "x-request-id": "req-001"}
    masked = _mask_sensitive(headers)
    assert masked["cookie"] == "***REDACTED***"
    assert masked["x-request-id"] == "req-001"


def test_mask_x_api_key():
    headers = {"x-api-key": "secret-key-123", "user-agent": "Mozilla/5.0"}
    masked = _mask_sensitive(headers)
    assert masked["x-api-key"] == "***REDACTED***"
    assert masked["user-agent"] == "Mozilla/5.0"


def test_mask_non_sensitive_headers_unchanged():
    headers = {
        "content-type": "application/json",
        "x-request-id": "req-abc",
        "accept": "application/json",
    }
    masked = _mask_sensitive(headers)
    assert masked == headers


def test_mask_empty_headers():
    assert _mask_sensitive({}) == {}


# ─── Tests _sign_entry ────────────────────────────────────────────────────────

def test_sign_entry_is_deterministic():
    entry = {"path": "/api/v1/auth/login", "method": "POST", "status": 200}
    secret = "test-secret"
    sig1 = _sign_entry(entry, secret)
    sig2 = _sign_entry(entry, secret)
    assert sig1 == sig2


def test_sign_entry_hex_string():
    entry = {"test": "value"}
    sig = _sign_entry(entry, "secret")
    assert len(sig) == 64  # SHA-256 -> 64 chars hex
    assert all(c in "0123456789abcdef" for c in sig)


def test_sign_entry_tamper_detectable():
    """Une modification de l'entrée invalide le HMAC."""
    entry = {"path": "/api/v1/auth", "status": 200, "user": "alice"}
    secret = "test-secret"
    sig_original = _sign_entry(entry, secret)

    entry_tampered = {**entry, "status": 201}  # Modification
    sig_tampered = _sign_entry(entry_tampered, secret)

    assert sig_original != sig_tampered


def test_sign_entry_different_secrets_different_sigs():
    entry = {"path": "/test", "status": 200}
    sig1 = _sign_entry(entry, "secret1")
    sig2 = _sign_entry(entry, "secret2")
    assert sig1 != sig2


def test_hmac_verification_offline():
    """Vérification HMAC offline selon la doc du module."""
    secret = "test-secret-key"
    entry = {
        "path": "/api/v1/auth/login",
        "method": "POST",
        "status": 200,
        "ip": "127.0.0.1",
    }
    signature = _sign_entry(entry, secret)

    # Vérification offline
    payload = json.dumps(entry, sort_keys=True, default=str)
    expected = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert expected == signature


# ─── Tests AuditLogMiddleware ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_middleware_passes_through():
    """Le middleware ne bloque pas les requêtes normales."""
    app = FastAPI()
    app.add_middleware(AuditLogMiddleware)

    @app.get("/api/v1/products")
    async def _products():
        return {"items": []}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/products")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_audit_middleware_allows_post():
    """Le middleware log mais ne bloque pas les POST."""
    app = FastAPI()
    app.add_middleware(AuditLogMiddleware)

    @app.post("/api/v1/auth/login")
    async def _login():
        return {"token": "abc"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/auth/login", json={"email": "test@test.com"})
    assert resp.status_code == 200
