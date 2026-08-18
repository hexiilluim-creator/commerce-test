from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import api.v1.settings as settings_module
from api.v1.settings import OemApiConfig, StockSourceConfig, get_oem_config, set_oem_config, set_stock_source, test_stock_source as run_test_stock_source


@pytest.fixture
def admin_role():
    token = settings_module.current_user_role.set("admin")
    yield
    settings_module.current_user_role.reset(token)


def db_with_store(store):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = store
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_set_stock_source_encrypts_config(admin_role):
    store = SimpleNamespace(stock_source_type=None, stock_source_config_enc=None)
    db = db_with_store(store)
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    with patch("api.v1.settings._sid", return_value=4), \
         patch("api.v1.settings.app_settings", SimpleNamespace(encrypt=lambda v: f"enc:{v}")), \
         patch("api.v1.settings._audit", new=AsyncMock()):
        data = await set_stock_source(StockSourceConfig(source_type="generic_api", config={"url": "https://stock.example"}), request, db)
    assert data == {"ok": True, "source_type": "generic_api"}
    assert store.stock_source_config_enc.startswith("enc:")
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_stock_source_validation_rejects_ssrf_and_missing_sheet(admin_role):
    store = SimpleNamespace()
    db = db_with_store(store)
    with patch("api.v1.settings._sid", return_value=4):
        with pytest.raises(HTTPException) as exc:
            await run_test_stock_source(StockSourceConfig(source_type="google_sheets", config={}), db)
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException) as exc:
            await run_test_stock_source(StockSourceConfig(source_type="woocommerce", config={"site_url": "http://127.0.0.1"}), db)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_stock_source_dashboard_count(admin_role):
    store = SimpleNamespace()
    db = db_with_store(store)
    count_result = MagicMock()
    count_result.scalar.return_value = 7
    db.execute.side_effect = [db.execute.return_value, count_result]
    with patch("api.v1.settings._sid", return_value=4):
        data = await run_test_stock_source(StockSourceConfig(source_type="dashboard"), db)
    assert data == {"ok": True, "message": "Dashboard connecté", "count": 7}


@pytest.mark.asyncio
async def test_get_and_set_oem_config(admin_role):
    store = SimpleNamespace(auto_parts_mode=False, nhtsa_enabled=True, tecdoc_api_key_enc=None, tecdoc_provider_id=None, autoiso_api_key_enc=None, stock_source_type="dashboard")
    db = db_with_store(store)
    with patch("api.v1.settings._sid", return_value=4):
        before = await get_oem_config(db)
    assert before["tecdoc_configured"] is False
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    with patch("api.v1.settings._sid", return_value=4), \
         patch("api.v1.settings.app_settings", SimpleNamespace(encrypt=lambda v: f"encrypted-{v}")), \
         patch("api.v1.settings._audit", new=AsyncMock()):
        data = await set_oem_config(OemApiConfig(tecdoc_api_key="key", tecdoc_provider_id="p1", auto_parts_mode=True, nhtsa_enabled=False), request, db)
    assert data["auto_parts_mode"] is True
    assert store.tecdoc_api_key_enc == "encrypted-key"
    assert store.tecdoc_provider_id == "p1"
    assert store.nhtsa_enabled is False


@pytest.mark.asyncio
async def test_store_completeness_reports_required_and_recommended(admin_role):
    from api.v1.settings import get_store_completeness
    store = SimpleNamespace(id=4, slug="demo", name="Demo", whatsapp_phone="+216", language="fr", ai_agent_prompt="hello", logo_url=None, description=None, support_email=None, whatsapp_access_token_enc="enc", whatsapp_phone_number_id="pid")
    db = db_with_store(store)
    product_result = MagicMock()
    product_result.scalar.return_value = 1
    db.execute.side_effect = [db.execute.return_value, product_result]
    with patch("api.v1.settings._sid", return_value=4):
        data = await get_store_completeness(db)
    assert data["is_online"] is True
    assert data["score"] == 100
    assert "logo_url" in [x["key"] for x in data["recommended_missing"]]


@pytest.mark.asyncio
async def test_public_store_returns_active_products():
    from api.v1.settings import get_public_store
    store = SimpleNamespace(id=4, slug="demo", is_active=True, name="Demo", whatsapp_phone="+216", language="fr")
    store_result = MagicMock()
    store_result.scalar_one_or_none.return_value = store
    products_result = MagicMock()
    products_result.scalars.return_value.all.return_value = [SimpleNamespace(id=1, name="Item", description=None, price=10, stock_qty=3, image_url=None, category=None, sku=None)]
    db = AsyncMock()
    db.execute.side_effect = [store_result, products_result]
    data = await get_public_store("demo", db)
    assert data["slug"] == "demo"
    assert data["product_count"] == 1
    assert data["products"][0]["name"] == "Item"
