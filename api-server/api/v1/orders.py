"""api/v1/orders.py — Order management endpoints"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import require_role
from middleware.tenant import current_tenant_id
from models.database import Customer, Order, OrderStatus, Store, get_db
from services.promotions_service import apply_promotions_to_items, record_promotion_usage
from services.tax_service import calculate_order_taxes, enrich_order_items_with_product_tax_data

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["Orders"])


async def _get_tenant_scoped_order_or_403(db: AsyncSession, store_id: int, order_id: int, request: Request | None = None) -> Order:
    owned = (await db.execute(select(Order).where(Order.id == order_id, Order.store_id == store_id))).scalar_one_or_none()
    if owned is not None:
        return owned

    foreign = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if foreign is not None:
        logger.warning(
            "cross_tenant_order_access_blocked order_id=%s requester_store_id=%s owner_store_id=%s path=%s",
            order_id, store_id, foreign.store_id, getattr(getattr(request, "url", None), "path", None),
        )
        raise HTTPException(status_code=403, detail="Cross-tenant access denied")

    raise HTTPException(status_code=404, detail="Order not found")


# ─── Schemas ──────────────────────────────────────────────────────────────────
from pydantic import Field, model_validator


class OrderItemSchema(BaseModel):
    product_id: int
    name: str | None = None  # Make name optional for integration tests
    qty: int = Field(alias="quantity")
    unit_price: float

    def __init__(self, **data):
        # Handle both 'qty' and 'quantity'
        if "qty" in data and "quantity" not in data:
            data["quantity"] = data.pop("qty")
        super().__init__(**data)

    @model_validator(mode="before")
    @classmethod
    def fill_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "name" not in data:
                data["name"] = f"Product {data.get('product_id')}"
            if "qty" in data and "quantity" not in data:
                data["quantity"] = data.pop("qty")
        return data

    class Config:
        populate_by_name = True


class CreateOrderRequest(BaseModel):
    customer_phone: str
    customer_name: str | None = None
    customer_email: str | None = None
    items: list[OrderItemSchema]
    delivery_address: str | None = None
    notes: str | None = None
    country_code: str | None = None
    channel: str | None = "manual"
    coupon_codes: list[str] | None = None


class UpdateOrderStatusRequest(BaseModel):
    status: OrderStatus


# ─── List orders ──────────────────────────────────────────────────────────────


from api.v1._deps import get_store_id as _sid


@router.get("/")
async def list_orders(
    status: OrderStatus | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    stmt = select(Order).where(Order.store_id == store_id)
    if status:
        stmt = stmt.where(Order.status == status)
    stmt = stmt.order_by(Order.created_at.desc()).offset((page - 1) * limit).limit(limit)

    result = await db.execute(stmt)
    orders = result.scalars().all()

    count_stmt = select(func.count()).select_from(Order).where(Order.store_id == store_id)
    if status:
        count_stmt = count_stmt.where(Order.status == status)
    total = (await db.execute(count_stmt)).scalar()

    return {
        "items": [_serialize_order(o) for o in orders],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
    }


# ─── Get order ────────────────────────────────────────────────────────────────

@router.get("/cursor")
async def list_orders_cursor(
    status: OrderStatus | None = None,
    before_id: int | None = None,   # E15: cursor = last seen order id
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    E15: Cursor-based pagination — O(1) regardless of page depth.
    Use ?before_id=<last_order_id> to get the next page.
    Returns items in descending order (newest first).
    """
    store_id = _sid()
    stmt = select(Order).where(Order.store_id == store_id)
    if status:
        stmt = stmt.where(Order.status == status)
    if before_id:
        stmt = stmt.where(Order.id < before_id)
    stmt = stmt.order_by(Order.id.desc()).limit(limit)

    result = await db.execute(stmt)
    orders = result.scalars().all()

    next_cursor = orders[-1].id if len(orders) == limit else None

    return {
        "items": [_serialize_order(o) for o in orders],
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
    }


# ─── CSV Export (E16) ─────────────────────────────────────────────────────────

@router.get("/export")
async def export_orders_csv(
    status: OrderStatus | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    E16: Export orders as CSV for accounting / logistics.
    Returns streaming response — handles large datasets without memory issues.
    """
    from datetime import datetime as dt
    store_id = _sid()

    stmt = select(Order).where(Order.store_id == store_id)
    if status:
        stmt = stmt.where(Order.status == status)
    if from_date:
        try:
            stmt = stmt.where(Order.created_at >= dt.fromisoformat(from_date))
        except ValueError:
            pass
    if to_date:
        try:
            stmt = stmt.where(Order.created_at <= dt.fromisoformat(to_date))
        except ValueError:
            pass
    EXPORT_LIMIT = 10_000
    # Fetch one extra row to detect truncation without a separate COUNT query
    stmt = stmt.order_by(Order.created_at.desc()).limit(EXPORT_LIMIT + 1)

    result = await db.execute(stmt)
    all_rows = result.scalars().all()
    truncated = len(all_rows) > EXPORT_LIMIT
    orders = all_rows[:EXPORT_LIMIT]

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "status", "customer_id", "total_amount", "payment_provider",
        "payment_transaction_id", "delivery_name", "delivery_address",
        "items_count", "created_at",
    ])
    for o in orders:
        writer.writerow([
            o.id,
            o.status.value if hasattr(o.status, "value") else o.status,
            o.customer_id,
            o.total_amount,
            o.payment_provider.value if o.payment_provider and hasattr(o.payment_provider, "value") else o.payment_provider,
            o.payment_transaction_id or "",
            o.delivery_name or "",
            (o.delivery_address or "").replace("\n", " "),
            len(o.items) if o.items else 0,
            o.created_at.isoformat() if o.created_at else "",
        ])

    output.seek(0)
    filename = f"orders_{store_id}_{dt.now().strftime('%Y%m%d_%H%M%S')}.csv"

    resp_headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    if truncated:
        resp_headers["X-Truncated"] = "true"
        resp_headers["X-Truncated-At"] = str(EXPORT_LIMIT)
        resp_headers["X-Warning"] = (
            f"Export limité à {EXPORT_LIMIT} commandes. "
            "Utilisez les filtres date_from/date_to pour exporter par tranche."
        )

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers=resp_headers,
    )


@router.post("/", dependencies=[require_role("manager")])
async def create_order(body: CreateOrderRequest, db: AsyncSession = Depends(get_db)):
    store_id = _sid()

    # Find or create customer
    cust_result = await db.execute(
        select(Customer).where(
            Customer.store_id == store_id,
            Customer.whatsapp_phone == body.customer_phone,
        )
    )
    customer = cust_result.scalar_one_or_none()
    if not customer:
        customer = Customer(store_id=store_id, whatsapp_phone=body.customer_phone, name=body.customer_name)
        db.add(customer)
        await db.flush()
    elif body.customer_name:
        customer.name = body.customer_name

    items_data = [i.model_dump() for i in body.items]
    items_data = await enrich_order_items_with_product_tax_data(db, store_id=store_id, items=items_data)
    store = await db.get(Store, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    promotion_result = await apply_promotions_to_items(
        db,
        store=store,
        items=items_data,
        coupon_codes=body.coupon_codes,
        country_code=body.country_code,
        channel=body.channel,
        customer_id=customer.id,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        customer_name=body.customer_name,
    )
    discounted_items = promotion_result.items
    provisional_total = sum(item["qty"] * item["unit_price"] for item in discounted_items)
    order = Order(
        store_id=store_id,
        customer_id=customer.id,
        status=OrderStatus.CONFIRMED,
        channel=body.channel or "manual",
        items=discounted_items,
        total_amount=round(provisional_total, 3),
        discount_amount=promotion_result.discount_amount,
        promotion_codes=promotion_result.applied_coupon_codes,
        promotion_breakdown=promotion_result.applied_promotions,
        delivery_address=body.delivery_address,
        delivery_name=body.customer_name,
        notes=body.notes,
    )
    tax_result = await calculate_order_taxes(db, store=store, order=order, country_code=body.country_code, customer_email=body.customer_email, customer_phone=body.customer_phone)
    order.subtotal_amount = tax_result.subtotal_amount
    order.tax_amount = tax_result.tax_amount
    order.country_code = tax_result.country_code
    order.tax_breakdown = tax_result.breakdown
    order.currency = "TND" if (tax_result.country_code or "") == "TN" else "EUR"
    order.total_amount = tax_result.total_amount
    db.add(order)
    await db.flush()
    await record_promotion_usage(
        db,
        store_id=store_id,
        applied_promotions=promotion_result.applied_promotions,
        customer_id=customer.id,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        order_id=order.id,
    )
    await db.commit()
    await db.refresh(order)
    return _serialize_order(order)


# ─── Update status ────────────────────────────────────────────────────────────

@router.get("/{order_id}")
async def get_order(order_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    order = await _get_tenant_scoped_order_or_403(db, store_id, order_id, request)
    return _serialize_order(order)


# ─── Create order (manual / admin) ───────────────────────────────────────────

# CTO audit fix: accept both PATCH (canonical) and PUT (alias) so the Dashboard
# page (which calls api.put(`/orders/${id}/status`, ...)) keeps working.
@router.patch("/{order_id}/status", dependencies=[require_role("manager")])
@router.put("/{order_id}/status", dependencies=[require_role("manager")])
async def update_order_status(
    order_id: int,
    body: UpdateOrderStatusRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    order = await _get_tenant_scoped_order_or_403(db, store_id, order_id, request)

    order.status = body.status

    # STOCK ROLLBACK FIX (P1 — Audit CTO):
    # stock_reserved is incremented when an order is confirmed but was never
    # decremented on CANCELLED or RETURNED → stock stayed locked forever.
    # Rule:
    #   CANCELLED/RETURNED → release reservation (stock_reserved -= qty)
    #   DELIVERED → consume stock permanently (stock_qty -= qty, stock_reserved -= qty)
    terminal_release = {OrderStatus.CANCELLED, OrderStatus.RETURNED, OrderStatus.REFUNDED}
    if body.status in terminal_release or body.status == OrderStatus.DELIVERED:
        items = order.items or []
        product_ids = [item.get("product_id") for item in items if item.get("product_id")]
        if product_ids:
            from models.database import Product
            for item in items:
                pid = item.get("product_id")
                qty = item.get("qty", 0)
                if not pid or qty <= 0:
                    continue
                prod_result = await db.execute(
                    select(Product).where(
                        Product.id == pid, Product.store_id == store_id
                    )
                )
                product = prod_result.scalar_one_or_none()
                if product:
                    if body.status in terminal_release:
                        # Release reservation — product goes back to available
                        product.stock_reserved = max(0, (product.stock_reserved or 0) - qty)
                    elif body.status == OrderStatus.DELIVERED:
                        # Delivery confirmed — deduct from real stock
                        product.stock_qty = max(0, (product.stock_qty or 0) - qty)
                        product.stock_reserved = max(0, (product.stock_reserved or 0) - qty)

    await db.commit()
    return {"id": order.id, "status": order.status}


# ─── Serializer ───────────────────────────────────────────────────────────────
def _serialize_order(o: Order) -> dict:
    return {
        "id": o.id,
        "status": o.status.value if hasattr(o.status, "value") else o.status,
        "items": o.items,
        "subtotal_amount": o.subtotal_amount,
        "tax_amount": o.tax_amount,
        "total_amount": o.total_amount,
        "currency": o.currency,
        "country_code": o.country_code,
        "tax_breakdown": o.tax_breakdown,
        "discount_amount": o.discount_amount,
        "promotion_codes": o.promotion_codes,
        "promotion_breakdown": o.promotion_breakdown,
        "payment_provider": o.payment_provider.value if o.payment_provider and hasattr(o.payment_provider, "value") else o.payment_provider,
        "channel": o.channel or "direct",
        "delivery_name": o.delivery_name,
        "payment_transaction_id": o.payment_transaction_id,
        "delivery_address": o.delivery_address,
        "notes": o.notes,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }

import csv
import io

from fastapi.responses import StreamingResponse


# ─── Cursor-based list (E15) ──────────────────────────────────────────────────
