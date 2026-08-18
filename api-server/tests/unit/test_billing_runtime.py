from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.v1.billing import CheckoutBody, _tenant_id_or_401, get_byok_status, get_public_plans, whatsapp_gate


def test_billing_schema_and_tenant_guard():
    body = CheckoutBody(plan_code="starter", success_url="https://ok", cancel_url="https://cancel")
    assert body.plan_code == "starter"
    with patch("api.v1.billing._sid", return_value=None):
        with pytest.raises(HTTPException) as exc:
            _tenant_id_or_401()
    assert exc.value.status_code == 401
    with patch("api.v1.billing._sid", return_value="7"):
        assert _tenant_id_or_401() == 7


@pytest.mark.asyncio
async def test_public_plans_and_whatsapp_gate():
    db = AsyncMock()
    with patch("api.v1.billing.list_plans_catalog", new=AsyncMock(return_value=[{"code": "starter"}])):
        assert await get_public_plans(db) == {"plans": [{"code": "starter"}]}
    snapshot = SimpleNamespace(has_feature=lambda feature: True, plan_code="pro_whatsapp")
    with patch("api.v1.billing._sid", return_value=7), patch("api.v1.billing.get_billing_snapshot", new=AsyncMock(return_value=snapshot)):
        data = await whatsapp_gate()
    assert data["enabled"] is True and data["plan_code"] == "pro_whatsapp"


@pytest.mark.asyncio
async def test_byok_status_is_explicitly_disabled():
    data = await get_byok_status()
    assert data["byok_enabled"] is False
    assert data["reason"] == "byok_removed_v15"
    assert "gpt-4o-mini" in data["providers_platform"]
