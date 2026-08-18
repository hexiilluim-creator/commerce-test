from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.asyncio


async def test_health_detailed_returns_coherent_circuit_breakers(async_client, monkeypatch):
    from api.v1 import health as health_module
    from services import circuit_breaker as circuit_breaker_module

    async def _ok_check():
        return {"status": "ok"}

    async def _ok_tuple():
        return ({"status": "ok"}, False)

    monkeypatch.setattr(health_module, "_check_database", _ok_check)
    monkeypatch.setattr(health_module, "_check_redis", _ok_check)
    monkeypatch.setattr(health_module, "_check_openai", _ok_check)
    monkeypatch.setattr(health_module, "_check_celery_queues", _ok_tuple)
    monkeypatch.setattr(health_module, "_check_disk", _ok_tuple)
    monkeypatch.setattr(health_module, "_check_celery_workers", _ok_tuple)
    monkeypatch.setattr(
        circuit_breaker_module,
        "list_breakers",
        lambda: [
            {"name": "openai", "state": "closed", "failures": 0, "opened_at": None},
            {"name": "stripe", "state": "open", "failures": 5, "opened_at": 123.0},
        ],
    )

    resp = await async_client.get(
        "/api/health/detailed",
        headers={"X-Internal-Token": os.environ["INTERNAL_HEALTH_TOKEN"]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "degraded"
    cb = data["components"]["circuit_breakers"]
    assert cb["status"] == "degraded"
    assert cb["count"] == 2
    assert cb["open_count"] == 1
    assert cb["breakers"]["openai"] == "closed"
    assert cb["breakers"]["stripe"] == "open"


async def test_super_admin_stats_rbac_and_payload(async_client, auth_headers):
    admin = await auth_headers("admin")
    denied = await async_client.get("/api/v1/super-admin/stats", headers=admin)
    assert denied.status_code == 403, denied.text

    super_admin = await auth_headers("super_admin")
    allowed = await async_client.get("/api/v1/super-admin/stats", headers=super_admin)
    assert allowed.status_code == 200, allowed.text
    payload = allowed.json()
    assert {
        "total_stores",
        "active_subscriptions",
        "total_revenue_monthly",
        "total_orders",
        "expiring_soon",
        "expired_count",
        "created_at",
        "expires_at",
        "features",
    }.issubset(payload.keys())
    assert isinstance(payload["features"], list)
    assert payload["expires_at"] is None
