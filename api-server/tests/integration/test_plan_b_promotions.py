from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import Store


@pytest.mark.asyncio
async def test_order_creation_applies_coupon_discount(
    async_client: AsyncClient,
    db_session: AsyncSession,
    auth_headers,
):
    headers = await auth_headers("admin")

    me = await async_client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    me.json()["store_id"]

    product_resp = await async_client.post(
        "/api/v1/products/",
        headers=headers,
        json={
            "name": "Filtre premium",
            "description": "Test promo",
            "price": 100,
            "stock_qty": 10,
            "category": "filters",
        },
    )
    assert product_resp.status_code == 201, product_resp.text
    product = product_resp.json()

    promo_resp = await async_client.post(
        "/api/v1/promotions/",
        headers=headers,
        json={
            "name": "SAVE10",
            "promotion_type": "coupon",
            "discount_type": "percentage",
            "discount_value": 10,
            "applies_to": "all",
            "is_active": True,
            "rules": [{"conditions": {"minimum_cart_amount": 50}}],
        },
    )
    assert promo_resp.status_code == 201, promo_resp.text
    promotion_id = promo_resp.json()["id"]

    coupon_resp = await async_client.post(
        "/api/v1/promotions/coupons",
        headers=headers,
        json={
            "promotion_id": promotion_id,
            "code": "SAVE10",
            "coupon_kind": "multi",
            "per_customer_limit": 1,
        },
    )
    assert coupon_resp.status_code == 201, coupon_resp.text

    order_resp = await async_client.post(
        "/api/v1/orders/",
        headers=headers,
        json={
            "customer_phone": "+21611111111",
            "customer_name": "Client Promo",
            "items": [
                {
                    "product_id": product["id"],
                    "name": product["name"],
                    "qty": 1,
                    "unit_price": 100,
                }
            ],
            "coupon_codes": ["SAVE10"],
            "channel": "storefront",
        },
    )
    assert order_resp.status_code == 200, order_resp.text
    data = order_resp.json()
    assert float(data["discount_amount"]) == pytest.approx(10.0, abs=0.01)
    assert data["promotion_codes"] == ["SAVE10"]
    assert float(data["total_amount"]) == pytest.approx(90.0, abs=0.02)
