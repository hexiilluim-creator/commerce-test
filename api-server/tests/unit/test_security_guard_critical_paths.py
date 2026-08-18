from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from security_overlay import guard


@pytest.fixture(autouse=True)
def clear_guard_state():
    guard._SNAPSHOT_CACHE.clear()
    guard._failopen_counters.clear()
    yield
    guard._SNAPSHOT_CACHE.clear()
    guard._failopen_counters.clear()


def snapshot(*, features=None, plan="business", paid=True, active=True):
    obj = SimpleNamespace(
        plan_code=plan,
        plan_label=plan.title(),
        is_paid=paid,
        is_active=active,
        expires_at=datetime(2027, 1, 1, tzinfo=UTC),
        features=set(features or {"crm.basic"}),
    )
    obj.has_feature = lambda feature: feature in obj.features
    return obj


@pytest.mark.asyncio
async def test_plan_access_refreshes_and_uses_stale_cache_on_provider_failure():
    s = snapshot(features={"marketing"})
    g = guard.SecurityGuard()
    with patch("security_overlay.guard.get_billing_snapshot", new=AsyncMock(return_value=s)):
        assert await g.check_plan_access(1, "marketing") is True
        assert await g.check_plan_access(1, "missing") is False
    with patch("security_overlay.guard.get_billing_snapshot", new=AsyncMock(side_effect=RuntimeError("down"))):
        assert await g.check_plan_access(1, "marketing") is True
        assert await g.check_plan_access(1, "missing") is False


@pytest.mark.asyncio
async def test_plan_access_fails_closed_without_cache():
    g = guard.SecurityGuard()
    with patch("security_overlay.guard.get_billing_snapshot", new=AsyncMock(side_effect=RuntimeError("down"))):
        assert await g.check_plan_access(2, "marketing") is False


@pytest.mark.asyncio
async def test_feature_or_403_allows_feature_and_rejects_missing_feature():
    g = guard.SecurityGuard()
    s = snapshot(features={"crm.basic"})
    with patch("security_overlay.guard.get_billing_snapshot", new=AsyncMock(return_value=s)):
        assert await g.check_feature_or_403(3, "crm.basic") is None
        with pytest.raises(HTTPException) as exc:
            await g.check_feature_or_403(3, "marketing")
    assert exc.value.status_code == 403
    assert exc.value.detail["upgrade_required"] is True


@pytest.mark.asyncio
async def test_feature_or_403_returns_503_when_billing_unavailable_without_cache():
    g = guard.SecurityGuard()
    with patch("security_overlay.guard.get_billing_snapshot", new=AsyncMock(side_effect=RuntimeError("down"))):
        with pytest.raises(HTTPException) as exc:
            await g.check_feature_or_403(4, "marketing")
    assert exc.value.status_code == 503
    assert exc.value.detail["error"] == "billing_service_unavailable"


@pytest.mark.asyncio
async def test_feature_or_403_uses_stale_cache_when_provider_fails():
    g = guard.SecurityGuard()
    s = snapshot(features={"crm.basic"})
    with patch("security_overlay.guard.get_billing_snapshot", new=AsyncMock(return_value=s)):
        await g.check_feature_or_403(5, "crm.basic")
    with patch("security_overlay.guard.get_billing_snapshot", new=AsyncMock(side_effect=RuntimeError("down"))):
        with pytest.raises(HTTPException) as exc:
            await g.check_feature_or_403(5, "marketing")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_check_credit_returns_provider_result_and_logs_denial_path():
    g = guard.SecurityGuard()
    with patch("security_overlay.guard.check_tenant_credit", new=AsyncMock(return_value=True)):
        assert await g.check_credit(6, "text", 1) is True
    with patch("security_overlay.guard.check_tenant_credit", new=AsyncMock(return_value=False)):
        assert await g.check_credit(6, "text", 1) is False


@pytest.mark.asyncio
async def test_check_credit_failopen_is_capped_per_tenant():
    g = guard.SecurityGuard()
    with patch("security_overlay.guard.check_tenant_credit", new=AsyncMock(side_effect=RuntimeError("redis down"))):
        results = [await g.check_credit(7, "text", 1) for _ in range(guard._FAILOPEN_MAX_PER_WINDOW + 1)]
    assert all(results[: guard._FAILOPEN_MAX_PER_WINDOW])
    assert results[-1] is False


@pytest.mark.asyncio
async def test_deduct_credit_calls_provider_and_swallows_provider_failure():
    g = guard.SecurityGuard()
    deduct = AsyncMock()
    with patch("security_overlay.guard.deduct_tenant_credit", new=deduct):
        assert await g.deduct_credit(8, "image", 10) is None
    deduct.assert_awaited_once_with(8, 10)
    with patch("security_overlay.guard.deduct_tenant_credit", new=AsyncMock(side_effect=RuntimeError("down"))):
        assert await g.deduct_credit(8, "image", 10) is None


@pytest.mark.asyncio
async def test_dump_stats_returns_snapshot_and_usage():
    g = guard.SecurityGuard()
    s = snapshot(features={"crm.basic", "marketing"})
    usage = {"remaining": 9, "used": 1}
    with patch("security_overlay.guard.get_billing_snapshot", new=AsyncMock(return_value=s)), patch(
        "security_overlay.guard.get_tenant_credit_stats", new=AsyncMock(return_value=usage)
    ):
        stats = await g.dump_stats(9)
    assert stats["plan_code"] == "business"
    assert stats["features"] == ["crm.basic", "marketing"]
    assert stats["expires_at"].startswith("2027-01-01")
    assert stats["ai_credits"] == usage


@pytest.mark.asyncio
async def test_dump_stats_handles_failure_with_error_payload():
    g = guard.SecurityGuard()
    with patch("security_overlay.guard.get_billing_snapshot", new=AsyncMock(side_effect=RuntimeError("down"))):
        result = await g.dump_stats(10)
    assert result == {"error": "down"}


def test_cache_expiration_and_eviction_helpers(monkeypatch):
    s = snapshot()
    guard._cache_set(11, s)
    assert guard._cache_get(11) is s
    monkeypatch.setattr(guard.time, "monotonic", lambda: 10**12)
    assert guard._cache_get(11) is None
    monkeypatch.setattr(guard, "_CACHE_MAX_SIZE", 2)
    monkeypatch.setattr(guard.time, "monotonic", lambda: 1.0)
    guard._cache_set(1, s)
    guard._cache_set(2, s)
    guard._cache_set(3, s)
    assert len(guard._SNAPSHOT_CACHE) <= 2
