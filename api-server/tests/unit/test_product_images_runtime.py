from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.v1 import product_images


@pytest.mark.asyncio
async def test_upload_product_image_success_and_quota():
    db = AsyncMock()
    user = SimpleNamespace(store_id=4)
    product = SimpleNamespace(store_id=4, image_count=0, images=[], image_url=None)
    store = SimpleNamespace(billing_plan_code="pro")
    db.get.side_effect = [product, store]
    file = SimpleNamespace(read=AsyncMock(return_value=b"img"), filename="a.jpg", content_type="image/jpeg")
    stored = {"url": "https://cdn/a.jpg", "storage_key": "k", "storage_backend": "s3"}
    with patch("api.v1.product_images._get_current_user_from_request", new=AsyncMock(return_value=user)), patch("api.v1.product_images.get_plan_by_code", new=AsyncMock(return_value={"features_json": {"max_product_images_per_product": 2}})), patch("api.v1.product_images.validate_and_store", new=AsyncMock(return_value=stored)):
        result = await product_images.upload_product_image(SimpleNamespace(), 10, file, db)
    assert result["image_count"] == 1
    assert product.image_url == stored["url"]


@pytest.mark.asyncio
async def test_upload_product_image_rejects_tenant_and_quota():
    db = AsyncMock()
    user = SimpleNamespace(store_id=4)
    product = SimpleNamespace(store_id=9, image_count=0, images=[], image_url=None)
    db.get.return_value = product
    with patch("api.v1.product_images._get_current_user_from_request", new=AsyncMock(return_value=user)):
        with pytest.raises(HTTPException) as exc:
            await product_images.upload_product_image(SimpleNamespace(), 10, SimpleNamespace(), db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_product_image_updates_primary_url():
    db = AsyncMock()
    user = SimpleNamespace(store_id=4)
    product = SimpleNamespace(store_id=4, images=["u1", "u2"], image_count=2, image_url="u1")
    store = SimpleNamespace(billing_plan_code="pro")
    db.get.side_effect = [product, store]
    with patch("api.v1.product_images._get_current_user_from_request", new=AsyncMock(return_value=user)), patch("api.v1.product_images.get_plan_by_code", new=AsyncMock(return_value={"features_json": {"max_product_images_per_product": 3}})):
        result = await product_images.delete_product_image(SimpleNamespace(), 10, 0, db)
    assert result["image_count"] == 1
    assert product.image_url == "u2"
