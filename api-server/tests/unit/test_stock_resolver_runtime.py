from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.stock_resolver import (
    StockItem, _search_local_stock, _search_external_stock, resolve_stock,
)


def test_stock_item_formatting_and_stock_state():
    in_stock = StockItem("Filtre", "REF1", 12.3456, 2)
    on_order = StockItem("Pompe", None, 20.0, 0)
    assert in_stock.is_in_stock() and "✅" in in_stock.format_wa()
    assert not on_order.is_in_stock() and "Sur commande" in on_order.format_wa()


@pytest.mark.asyncio
async def test_local_search_empty_terms_and_db_failure_are_safe():
    db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("db")))
    assert await _search_local_stock(db, 1, [], ["x"], []) == []
    assert await _search_local_stock(db, 1, ["ABC"], [], []) == []


@pytest.mark.asyncio
async def test_local_search_maps_reserved_stock_and_product_fields():
    product = SimpleNamespace(name="Plaquette", external_code="ABC", price=Decimal("18.5"), stock_qty=5,
                              stock_reserved=2, image_url="/img", id=9)
    result = MagicMock(); result.scalars.return_value.all.return_value = [product]
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    items = await _search_local_stock(db, 1, ["ABC"], ["plaquette"], ["Renault"])
    assert len(items) == 1 and items[0].stock_qty == 3 and items[0].product_id == 9
    assert items[0].source == "local"


@pytest.mark.asyncio
async def test_external_stock_no_url_and_ssrf_block_are_fail_closed():
    assert await _search_external_stock(SimpleNamespace(id=1, stock_api_url=None), ["A"], []) == []
    store = SimpleNamespace(id=1, stock_api_url="http://169.254.169.254", stock_api_key_enc=None)
    with patch("services.ssrf_guard.assert_safe_external_url", side_effect=__import__("services.ssrf_guard", fromlist=["SSRFBlocked"]).SSRFBlocked("blocked")):
        assert await _search_external_stock(store, ["A"], []) == []


@pytest.mark.asyncio
async def test_external_stock_success_and_http_failure_are_safe():
    response = httpx.Response(200, request=httpx.Request("GET", "https://stock.example/search"), json={"items": [{"name": "Disque", "reference": "R1", "price": "22.5", "stock": 4, "image_url": "/d"}]})
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, *args, **kwargs): return response
    store = SimpleNamespace(id=1, stock_api_url="https://stock.example", stock_api_key_enc=None)
    with patch("services.ssrf_guard.assert_safe_external_url", return_value=None), \
         patch("services.stock_resolver.httpx.AsyncClient", return_value=Client()):
        items = await _search_external_stock(store, ["R1"], ["disque"])
    assert items[0].price == 22.5 and items[0].source == "external"
    failure = httpx.Response(503, request=httpx.Request("GET", "https://stock.example/search"))
    class FailingClient(Client):
        async def get(self, *args, **kwargs): return failure
    with patch("services.ssrf_guard.assert_safe_external_url", return_value=None), \
         patch("services.stock_resolver.httpx.AsyncClient", return_value=FailingClient()):
        assert await _search_external_stock(store, [], []) == []


@pytest.mark.asyncio
async def test_resolve_stock_merges_deduplicates_and_sorts():
    local = [StockItem("Local", "DUP", 30, 0), StockItem("Cheap", "L", 5, 2)]
    external = [StockItem("External duplicate", "DUP", 1, 4, source="external"), StockItem("New", "E", 8, 1, source="external")]
    with patch("services.stock_resolver._search_local_stock", new=AsyncMock(return_value=local)), \
         patch("services.stock_resolver._search_external_stock", new=AsyncMock(return_value=external)):
        out = await resolve_stock(SimpleNamespace(), SimpleNamespace(id=1), ["D"], [], [])
    assert [item.reference for item in out] == ["L", "E", "DUP"]
    assert len(out) == 3
