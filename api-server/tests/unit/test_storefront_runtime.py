import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace
from fastapi import HTTPException

import pytest
from pydantic import ValidationError

from api.v1.storefront import (
    StorefrontOrderRequest,
    StorefrontPreviewItem,
    _catalog_cache_key,
    _cursor_decode,
    _cursor_encode,
    _image_sources,
    _cache_get,
    _cache_set,
    invalidate_catalog_cache, get_storefront, get_storefront_products,
    create_storefront_order, preview_storefront_promotions,
    StorefrontPromotionPreviewRequest,
)


def test_storefront_cursor_roundtrip_and_invalid_token():
    token = _cursor_encode({"id": 42, "created": "2026-08-14"})
    assert _cursor_decode(token) == {"id": 42, "created": "2026-08-14"}
    assert _cursor_decode(None) is None
    assert _cursor_decode("not-valid") is None


def test_storefront_cache_key_and_image_variants():
    key = _catalog_cache_key(7, "brakes", {"page": 1})
    assert key.startswith("storefront:catalog:7:cat=brakes:h=")
    assert _image_sources(None)["primary"] is None
    variants = _image_sources("https://cdn.example/p.png?x=1")
    assert variants["webp"].endswith("&fmt=webp")
    assert variants["avif"].endswith("&fmt=avif")


def test_storefront_order_schema_rejects_bad_phone_and_accepts_item():
    item = StorefrontPreviewItem(name="Brake pad", qty=2, unit_price=Decimal("12.50"))
    order = StorefrontOrderRequest(customer_phone="216123456", items=[item])
    assert order.country_code == "TN"
    with pytest.raises(ValidationError):
        StorefrontOrderRequest(customer_phone="x", items=[item])


@pytest.mark.asyncio
async def test_storefront_cache_helpers_fail_safe_without_redis():
    with patch("api.v1.storefront._get_redis_safe", new=AsyncMock(return_value=None)):
        assert await _cache_get("missing") is None
        assert await _cache_set("k", {"x": 1}) is None
        assert await invalidate_catalog_cache(7) == 0


@pytest.mark.asyncio
async def test_storefront_cache_helpers_roundtrip_and_invalidate():
    redis = AsyncMock()
    redis.get.return_value = json.dumps({"items": [1]})
    redis.scan.side_effect = [(0, ["storefront:catalog:7:a"])]
    redis.delete.return_value = 1
    with patch("api.v1.storefront._get_redis_safe", new=AsyncMock(return_value=redis)):
        assert await _cache_get("k") == {"items": [1]}
        await _cache_set("k", {"x": 1}, ttl=30)
        assert await invalidate_catalog_cache(7) == 1
    redis.setex.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_storefront_returns_public_contract_and_404():
    store = SimpleNamespace(id=7, name="Garage", slug="garage", whatsapp_phone="21600000", language="fr", is_active=True, created_at=None)
    result = MagicMock(); result.scalar_one_or_none.return_value = store
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    out = await get_storefront("garage", db=db)
    assert out["id"] == 7 and out["slug"] == "garage" and out["currency"] == "TND"
    missing = MagicMock(); missing.scalar_one_or_none.return_value = None; db.execute = AsyncMock(return_value=missing)
    with pytest.raises(HTTPException) as exc:
        await get_storefront("missing", db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_storefront_products_cache_miss_serializes_products_and_cursor():
    store = SimpleNamespace(id=7, currency="TND", country="TN")
    store_result = MagicMock(); store_result.scalar_one_or_none.return_value = store
    product = SimpleNamespace(id=3, name="Pad", description=None, price=Decimal("12.5"), category="auto", stock_qty=2,
                              created_at=None, images=[], image_url="https://cdn/p.png")
    product_result = MagicMock(); product_result.scalars.return_value.all.return_value = [product]
    db = SimpleNamespace(execute=AsyncMock(side_effect=[store_result, MagicMock(), MagicMock(), product_result]))
    with patch("api.v1.storefront._cache_get", new=AsyncMock(return_value=None)), \
         patch("api.v1.storefront._cache_set", new=AsyncMock()), \
         patch("api.v1.storefront.preview_product_promo_price", new=AsyncMock(return_value=None)):
        out = await get_storefront_products("7", limit=12, db=db)
    assert out["cache"] == "MISS" and out["products"][0]["price"] == 12.5
    assert out["products"][0]["images"][0]["webp"].endswith("?fmt=webp")


@pytest.mark.asyncio
async def test_create_order_rejects_unavailable_product_after_store_context():
    store = SimpleNamespace(id=7, country="TN", currency="TND")
    store_result = MagicMock(); store_result.scalar_one_or_none.return_value = store
    products = MagicMock(); products.scalars.return_value.all.return_value = []
    db = SimpleNamespace(execute=AsyncMock(side_effect=[store_result, MagicMock(), MagicMock(), products]))
    body = StorefrontOrderRequest(customer_phone="216123456", items=[StorefrontPreviewItem(product_id=99, name="Pad", qty=1, unit_price=Decimal("1"))])
    with pytest.raises(HTTPException) as exc:
        await create_storefront_order("7", body, db=db)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_preview_promotions_applies_tax_contract():
    store = SimpleNamespace(id=7)
    store_result = MagicMock(); store_result.scalar_one_or_none.return_value = store
    db = SimpleNamespace(execute=AsyncMock(side_effect=[store_result, MagicMock(), MagicMock()]))
    promo = SimpleNamespace(items=[{"name": "Pad", "qty": 1, "unit_price": Decimal("10")}], discount_amount=Decimal("1"), applied_promotions=[{"code": "X"}], applied_coupon_codes=["X"])
    tax = SimpleNamespace(as_dict=lambda: {"subtotal": 9, "tax": 1, "total": 10})
    body = StorefrontPromotionPreviewRequest(items=[StorefrontPreviewItem(name="Pad", qty=1, unit_price=Decimal("10"))], country_code="TN")
    with patch("api.v1.storefront.apply_promotions_to_items", new=AsyncMock(return_value=promo)), \
         patch("api.v1.storefront.calculate_taxes_for_items", new=AsyncMock(return_value=tax)):
        out = await preview_storefront_promotions("7", body, db=db)
    assert out["discount_amount"] == 1.0 and out["applied_coupon_codes"] == ["X"] and out["pricing"]["total"] == 10
