from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services import ai_guardrails as ag


@pytest.fixture(autouse=True)
def clear_memory():
    ag._MEMORY_CREDITS.clear()
    ag._MEMORY_USED.clear()
    yield
    ag._MEMORY_CREDITS.clear()
    ag._MEMORY_USED.clear()


@pytest.mark.asyncio
async def test_keys_and_zero_or_negative_cost_rules():
    assert ag._credit_key(4).startswith("ai_credits:remaining:4:")
    assert ag._used_key(4).startswith("ai_credits:used:4:")
    assert ag._allocated_key(4).startswith("ai_credits:allocated:4:")
    with patch("services.ai_guardrails._get_redis", new=AsyncMock(return_value=None)), patch(
        "services.ai_guardrails._get_plan_quota", new=AsyncMock(return_value=10)
    ):
        assert await ag.check_tenant_credit(4, 0) is True
        assert await ag.deduct_tenant_credit(4, 0) is True


@pytest.mark.asyncio
async def test_check_credit_handles_free_plan_and_memory_remaining():
    with patch("services.ai_guardrails._get_redis", new=AsyncMock(return_value=None)), patch(
        "services.ai_guardrails._get_plan_quota", new=AsyncMock(return_value=0)
    ):
        assert await ag.check_tenant_credit(1, 1) is False
    with patch("services.ai_guardrails._get_redis", new=AsyncMock(return_value=None)), patch(
        "services.ai_guardrails._get_plan_quota", new=AsyncMock(return_value=10)
    ):
        assert await ag.check_tenant_credit(2, 10) is True
        assert await ag.check_tenant_credit(2, 11) is False


@pytest.mark.asyncio
async def test_check_credit_negative_quota_is_unlimited():
    with patch("services.ai_guardrails._get_redis", new=AsyncMock(return_value=None)), patch(
        "services.ai_guardrails._get_plan_quota", new=AsyncMock(return_value=-1)
    ):
        assert await ag.check_tenant_credit(3, 999999) is True


@pytest.mark.asyncio
async def test_deduct_uses_memory_fallback_and_persists_ledger():
    persist = AsyncMock()
    with patch("services.ai_guardrails._get_redis", new=AsyncMock(return_value=None)), patch(
        "services.ai_guardrails._get_plan_quota", new=AsyncMock(return_value=10),
    ), patch("services.ai_guardrails._persist_credit_event", new=persist):
        assert await ag.deduct_tenant_credit(5, 3) is True
        stats = await ag.get_tenant_credit_stats(5)
    assert stats["remaining"] == 7
    assert stats["used"] == 3
    assert stats["credits_percent_used"] == 30.0
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_deduct_clamps_memory_balance_at_zero():
    with patch("services.ai_guardrails._get_redis", new=AsyncMock(return_value=None)), patch(
        "services.ai_guardrails._get_plan_quota", new=AsyncMock(return_value=2),
    ), patch("services.ai_guardrails._persist_credit_event", new=AsyncMock()):
        assert await ag.deduct_tenant_credit(6, 10) is True
        stats = await ag.get_tenant_credit_stats(6)
    assert stats["remaining"] == 0
    assert stats["used"] == 10


@pytest.mark.asyncio
async def test_stats_reports_allocated_and_period_for_empty_account():
    with patch("services.ai_guardrails._get_redis", new=AsyncMock(return_value=None)), patch(
        "services.ai_guardrails._get_plan_quota", new=AsyncMock(return_value=25)
    ):
        stats = await ag.get_tenant_credit_stats(7)
    assert stats["store_id"] == 7
    assert stats["allocated"] == 25
    assert stats["remaining"] == 25
    assert stats["used"] == 0
    assert len(stats["period"]) == 6


@pytest.mark.asyncio
async def test_add_credits_supports_topup_bonus_and_nonpositive_amount():
    persist = AsyncMock()
    with patch("services.ai_guardrails._get_redis", new=AsyncMock(return_value=None)), patch(
        "services.ai_guardrails._get_plan_quota", new=AsyncMock(return_value=10),
    ), patch("services.ai_guardrails._get_db_credit_state", new=AsyncMock(return_value=(4, 2))), patch(
        "services.ai_guardrails._persist_credit_event", new=persist
    ):
        assert await ag.add_tenant_credits(8, 0) == 4
        assert await ag.add_tenant_credits(8, 5, "top_up") == 9
        assert await ag.add_tenant_credits(8, 2, "unknown") == 6
    assert persist.await_count == 2


@pytest.mark.asyncio
async def test_add_credits_allocate_uses_zero_db_balance_when_new():
    with patch("services.ai_guardrails._get_redis", new=AsyncMock(return_value=None)), patch(
        "services.ai_guardrails._get_plan_quota", new=AsyncMock(return_value=20),
    ), patch("services.ai_guardrails._get_db_credit_state", new=AsyncMock(return_value=(None, 0))), patch(
        "services.ai_guardrails._persist_credit_event", new=AsyncMock()
    ):
        assert await ag.add_tenant_credits(9, 20, "monthly_alloc") == 20


@pytest.mark.asyncio
async def test_reset_monthly_credits_resets_memory_and_persists_event():
    persist = AsyncMock()
    with patch("services.ai_guardrails._get_redis", new=AsyncMock(return_value=None)), patch(
        "services.ai_guardrails._get_plan_quota", new=AsyncMock(return_value=30),
    ), patch("services.ai_guardrails._persist_credit_event", new=persist):
        ag._MEMORY_CREDITS[ag._credit_key(10)] = 1
        ag._MEMORY_USED[ag._used_key(10)] = 99
        assert await ag.reset_monthly_credits(10) == 30
        stats = await ag.get_tenant_credit_stats(10)
    assert stats["remaining"] == 30
    assert stats["used"] == 0
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_shared_remaining_uses_db_outside_dev_and_quota_when_missing():
    with patch("services.ai_guardrails._allow_memory_fallback", return_value=False), patch(
        "services.ai_guardrails._get_db_credit_state", new=AsyncMock(return_value=(6, 4))
    ):
        assert await ag._shared_remaining_balance(11, 20) == 6
    with patch("services.ai_guardrails._allow_memory_fallback", return_value=False), patch(
        "services.ai_guardrails._get_db_credit_state", new=AsyncMock(return_value=(None, 0))
    ):
        assert await ag._shared_remaining_balance(11, 20) == 20
