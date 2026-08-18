from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.v1.orders import (
    CreateOrderRequest, OrderItemSchema, UpdateOrderStatusRequest,
    _get_tenant_scoped_order_or_403, _serialize_order, list_orders_cursor,
    export_orders_csv,
)
from models.database import OrderStatus


def _order(order_id=1, status=OrderStatus.CONFIRMED):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(id=order_id, status=status, items=[{"product_id": 2, "qty": 1}], subtotal_amount=10, tax_amount=2, total_amount=12, currency="TND", country_code="TN", tax_breakdown={}, discount_amount=0, promotion_codes=[], promotion_breakdown=[], payment_provider=None, channel=None, delivery_name="A", payment_transaction_id=None, delivery_address="x\ny", notes=None, created_at=now, updated_at=now, customer_id=3, store_id=4)


def test_order_schemas_and_serializer_contract():
    item = OrderItemSchema(product_id=1, qty=2, unit_price=3.5)
    assert item.name == "Product 1" and item.qty == 2
    req = CreateOrderRequest(customer_phone="216", items=[{"product_id": 1, "quantity": 1, "unit_price": 2}])
    assert req.channel == "manual"
    data = _serialize_order(_order())
    assert data["channel"] == "direct" and data["delivery_address"] == "x\ny"
    assert UpdateOrderStatusRequest(status=OrderStatus.CANCELLED).status == OrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_tenant_scoped_order_allows_owned_and_rejects_foreign_or_missing():
    db = AsyncMock(); owned = _order()
    first = MagicMock(); first.scalar_one_or_none.return_value = owned
    db.execute.return_value = first
    assert await _get_tenant_scoped_order_or_403(db, 4, 1) is owned
    foreign = _order(); foreign.store_id = 9
    r1 = MagicMock(); r1.scalar_one_or_none.return_value = None
    r2 = MagicMock(); r2.scalar_one_or_none.return_value = foreign
    db.execute.side_effect = [r1, r2]
    with pytest.raises(HTTPException) as exc: await _get_tenant_scoped_order_or_403(db, 4, 1)
    assert exc.value.status_code == 403
    r3 = MagicMock(); r3.scalar_one_or_none.return_value = None
    r4 = MagicMock(); r4.scalar_one_or_none.return_value = None
    db.execute.side_effect = [r3, r4]
    with pytest.raises(HTTPException) as exc: await _get_tenant_scoped_order_or_403(db, 4, 1)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_cursor_listing_sets_next_cursor_only_when_full_page():
    db = AsyncMock(); rows = [_order(5), _order(4)]
    result = MagicMock(); result.scalars.return_value.all.return_value = rows; db.execute.return_value = result
    with patch("api.v1.orders._sid", return_value=4):
        out = await list_orders_cursor(limit=2, db=db)
    assert out["next_cursor"] == 4 and out["has_more"] is True
    result.scalars.return_value.all.return_value = rows[:1]
    with patch("api.v1.orders._sid", return_value=4):
        out = await list_orders_cursor(limit=2, db=db)
    assert out["next_cursor"] is None and out["has_more"] is False


@pytest.mark.asyncio
async def test_export_orders_csv_escapes_newlines_and_returns_stream():
    db = AsyncMock(); result = MagicMock(); result.scalars.return_value.all.return_value = [_order()]; db.execute.return_value = result
    with patch("api.v1.orders._sid", return_value=4):
        response = await export_orders_csv(db=db)
    chunks = [c async for c in response.body_iterator]
    text = b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks).decode()
    assert "id,status" in text and "x y" in text and response.media_type == "text/csv"
