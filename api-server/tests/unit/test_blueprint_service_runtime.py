from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.blueprint_service import BlueprintService


def _result(value):
    result = MagicMock()
    if isinstance(value, list):
        result.scalars.return_value.all.return_value = value
    else:
        result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_list_and_apply_blueprint_serializes_and_applies_overrides():
    db = AsyncMock()
    service = BlueprintService(db)
    bp = SimpleNamespace(id="auto", name="Automotive", description="Cars", icon="car", default_business_type="auto", default_service_category="parts", default_ai_prompt="default", modules_enabled=["catalog"], ui_visibility={}, quotas={}, initial_data={})
    db.execute.return_value = _result([bp])
    listed = await service.list_blueprints(4)
    assert listed[0]["id"] == "auto"

    store = SimpleNamespace(id=4, ai_agent_prompt=None, business_type=None, service_category=None, extra_config={"old": True})
    await service.apply_blueprint_to_store(store, bp, {"ai_agent_prompt": "custom", "extra_modules": ["crm"]})
    assert store.ai_agent_prompt == "custom"
    assert "crm" in store.extra_config["modules_enabled"]


@pytest.mark.asyncio
async def test_apply_blueprint_errors_and_success_contract():
    db = AsyncMock()
    service = BlueprintService(db)
    db.get.return_value = None
    with pytest.raises(ValueError, match="Store"):
        await service.apply_blueprint(1, "auto")

    store = SimpleNamespace(id=1, ai_agent_prompt=None, business_type=None, service_category=None, extra_config=None)
    db.get.return_value = store
    db.execute.return_value = _result(None)
    with pytest.raises(ValueError, match="Blueprint"):
        await service.apply_blueprint(1, "missing")

    bp = SimpleNamespace(id="auto", name="Auto", modules_enabled=["catalog"], default_business_type=None, default_service_category=None, default_ai_prompt=None, ui_visibility={}, quotas={}, initial_data={})
    db.execute.return_value = _result(bp)
    db.flush = AsyncMock()
    result = await service.apply_blueprint(1, "auto")
    assert result["applied"] is True and result["modules_enabled"] == ["catalog"]
