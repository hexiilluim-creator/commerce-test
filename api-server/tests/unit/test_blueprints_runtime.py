from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.v1.blueprints import get_blueprint, get_my_blueprint, list_blueprints, select_blueprint, customize_blueprint
from models.blueprints import StoreBlueprintSelect


def _result(value):
    r = MagicMock()
    if isinstance(value, list):
        r.scalars.return_value.all.return_value = value
    else:
        r.scalar_one_or_none.return_value = value
    return r


@pytest.mark.asyncio
async def test_list_and_lookup_blueprints():
    db = AsyncMock()
    bp = SimpleNamespace(id=1, name="auto")
    db.execute.return_value = _result([bp])
    assert await list_blueprints(db) == [bp]
    db.execute.return_value = _result(bp)
    assert await get_blueprint("1", db) is bp
    db.execute.return_value = _result(None)
    with pytest.raises(HTTPException) as exc:
        await get_blueprint("missing", db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_my_store_and_customize_require_selection():
    db = AsyncMock()
    store = SimpleNamespace(id=4)
    db.execute.return_value = _result(None)
    assert await get_my_blueprint(store, db) is None
    with pytest.raises(HTTPException) as exc:
        await customize_blueprint({"x": True}, store, db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_select_blueprint_creates_and_applies_configuration():
    db = AsyncMock()
    store = SimpleNamespace(id=4)
    blueprint = SimpleNamespace(id=2)
    db.execute.side_effect = [_result(blueprint), _result(None)]
    db.refresh = AsyncMock()
    service = MagicMock()
    service.apply_blueprint_to_store = AsyncMock()
    with patch("api.v1.blueprints.BlueprintService", return_value=service):
        result = await select_blueprint(StoreBlueprintSelect(blueprint_id="2", custom_config={"tone": "formal"}), store, db)
    assert result.blueprint_id == "2"
    service.apply_blueprint_to_store.assert_awaited_once()
    db.commit.assert_awaited_once()

    db.execute.side_effect = None
    db.execute.return_value = _result(None)
    with pytest.raises(HTTPException) as exc:
        await select_blueprint(StoreBlueprintSelect(blueprint_id="9"), store, db)
    assert exc.value.status_code == 404
