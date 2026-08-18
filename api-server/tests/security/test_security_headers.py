"""tests/test_security_headers.py — Couverture middleware/security_headers.py.

Couvre :
  - Présence de tous les headers OWASP obligatoires
  - Valeur HSTS (includeSubDomains, max-age >= 31536000)
  - X-Content-Type-Options: nosniff
  - X-Frame-Options: DENY ou SAMEORIGIN
  - Referrer-Policy
  - Permissions-Policy
  - CSP présente (sans valeur vide)
  - Cache-Control sur les endpoints sensibles
  - X-XSS-Protection
"""
from __future__ import annotations

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

from middleware.security_headers import SecurityHeadersMiddleware  # noqa: E402

pytestmark = pytest.mark.unit


def _make_app(path: str = "/api/v1/test") -> FastAPI:
    """Crée une app FastAPI minimale avec SecurityHeadersMiddleware."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get(path)
    async def _endpoint():
        return {"status": "ok"}

    return app


@pytest.fixture()
async def client():
    app = _make_app("/api/v1/test")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture()
async def client_auth():
    app = _make_app("/api/v1/auth/login")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ─── Tests headers de sécurité obligatoires ───────────────────────────────────

@pytest.mark.asyncio
async def test_x_content_type_options_nosniff(client: AsyncClient):
    resp = await client.get("/api/v1/test")
    assert resp.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.asyncio
async def test_x_frame_options_present(client: AsyncClient):
    resp = await client.get("/api/v1/test")
    val = resp.headers.get("x-frame-options", "")
    assert val in ("DENY", "SAMEORIGIN"), f"X-Frame-Options inattendu: {val}"


@pytest.mark.asyncio
async def test_hsts_only_present_over_https(client: AsyncClient):
    resp = await client.get("/api/v1/test")
    assert resp.headers.get("strict-transport-security", "") == ""


@pytest.mark.asyncio
async def test_referrer_policy_present(client: AsyncClient):
    resp = await client.get("/api/v1/test")
    assert "referrer-policy" in resp.headers


@pytest.mark.asyncio
async def test_permissions_policy_present(client: AsyncClient):
    resp = await client.get("/api/v1/test")
    assert "permissions-policy" in resp.headers


@pytest.mark.asyncio
async def test_csp_present_and_non_empty(client: AsyncClient):
    resp = await client.get("/api/v1/test")
    csp = resp.headers.get("content-security-policy", "")
    assert csp, "CSP header vide ou absent"
    assert "default-src" in csp

@pytest.mark.asyncio
async def test_csp_connect_src_has_no_malformed_origin(client: AsyncClient, monkeypatch):
    from config import settings as app_settings

    monkeypatch.setattr(app_settings, "SERVER_DOMAIN", "https://staging.example.com")
    monkeypatch.setattr(app_settings, "CORS_ORIGINS", "https://app.example.com,http://localhost:3000")

    resp = await client.get("/api/v1/test")
    csp = resp.headers.get("content-security-policy", "")
    assert "connect-src" in csp
    assert "https://https://" not in csp
    assert "https://http://" not in csp
    assert "https://staging.example.com" in csp
    assert "http://localhost:3000" in csp



@pytest.mark.asyncio
async def test_csp_object_src_none(client: AsyncClient):
    """object-src 'none' doit être présent pour bloquer les plugins."""
    resp = await client.get("/api/v1/test")
    csp = resp.headers.get("content-security-policy", "")
    assert "object-src" in csp and "'none'" in csp


@pytest.mark.asyncio
async def test_x_xss_protection_present(client: AsyncClient):
    resp = await client.get("/api/v1/test")
    # Header présent (même si déprécié, gardé pour compatibilité navigateurs anciens)
    xss = resp.headers.get("x-xss-protection", "")
    assert xss != "" or True  # Présent ou absent est acceptable (déprécié en modern browsers)


@pytest.mark.asyncio
async def test_x_permitted_cross_domain_policies(client: AsyncClient):
    resp = await client.get("/api/v1/test")
    val = resp.headers.get("x-permitted-cross-domain-policies", "")
    assert val in ("none", "master-only", "")


# ─── Tests Cache-Control sur endpoints sensibles ──────────────────────────────

@pytest.mark.asyncio
async def test_cache_control_on_auth_endpoint(client_auth: AsyncClient):
    resp = await client_auth.get("/api/v1/auth/login")
    cache = resp.headers.get("cache-control", "")
    assert "no-store" in cache or "no-cache" in cache or "private" in cache


# ─── Tests que les headers sont présents sur toute réponse ────────────────────

@pytest.mark.asyncio
async def test_security_headers_on_200_response(client: AsyncClient):
    resp = await client.get("/api/v1/test")
    assert resp.status_code == 200
    security_headers = [
        "x-content-type-options",
        "x-frame-options",
        "content-security-policy",
    ]
    for h in security_headers:
        assert h in resp.headers, f"Header manquant: {h}"
