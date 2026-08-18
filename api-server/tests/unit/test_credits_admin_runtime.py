from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.v1.credits_admin import BonusBody, RenewalBody, _period_end, _period_start, _require_internal_token


def test_credit_admin_schemas_enforce_bonus_bounds():
    body = BonusBody(tenant_id=4, credits=100, reason="service gesture")
    assert body.created_by == "admin"
    assert RenewalBody(dry_run=True).dry_run is True
    with pytest.raises(ValueError):
        BonusBody(tenant_id=4, credits=0, reason="short")
    with pytest.raises(ValueError):
        BonusBody(tenant_id=4, credits=1, reason="x")


def test_period_helpers_return_current_month_utc_bounds():
    start = _period_start()
    end = _period_end()
    assert start.tzinfo == UTC
    assert start.day == 1 and start.hour == 0
    assert end.tzinfo == UTC
    assert end.hour == 23 and end.minute == 59 and end.second == 59
    assert end >= start


def test_internal_token_auth_distinguishes_missing_and_invalid():
    request = SimpleNamespace(state=SimpleNamespace(user_id=None, role=None))
    with pytest.raises(HTTPException) as missing:
        _require_internal_token(request, None)
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException) as invalid:
        _require_internal_token(request, "bad")
    assert invalid.value.status_code == 403


@pytest.mark.asyncio
async def test_trigger_renewal_all_handles_empty_and_dry_run():
    from api.v1 import credits_admin
    db = AsyncMock()
    with patch("api.v1.credits_admin._get_active_tenants", new=AsyncMock(return_value=[])):
        empty = await credits_admin.trigger_renewal_all(credits_admin.RenewalBody(), db)
    assert empty["status"] == "no_active_tenants"

    db = AsyncMock()
    with patch("api.v1.credits_admin._get_active_tenants", new=AsyncMock(return_value=[(4, "pro")])), patch("api.v1.credits_admin.get_plan_spec", return_value=SimpleNamespace(monthly_ai_credits=1000)):
        result = await credits_admin.trigger_renewal_all(credits_admin.RenewalBody(dry_run=True), db)
    assert result["status"] == "done"
    assert result["renewed"][0]["credits"] == 1000
    assert result["renewed"][0]["dry_run"] is True
    db.commit.assert_not_awaited()
