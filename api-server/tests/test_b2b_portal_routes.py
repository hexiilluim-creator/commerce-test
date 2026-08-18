from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.v1.b2b_portal import router
from middleware.tenant import current_tenant_id
from models.b2b_portal import CompanyAccount
from models.database import Base, Product, Store, get_db
from security_overlay.billing_overlay import BillingSnapshot


def _build_app(Session, role: str = "admin") -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def inject_auth(request: Request, call_next):
        token = current_tenant_id.set(1)
        request.state.jwt_payload = {"role": role, "user_id": 7}
        request.state.user_id = 7
        request.state.role = role
        try:
            return await call_next(request)
        finally:
            current_tenant_id.reset(token)

    async def override_get_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(router)
    return app


async def _seed_db(Session) -> None:
    async with Session() as session:
        store = Store(id=1, name="AC", slug="ac-route", default_tax_country="FR", country="FR", tax_inclusive_pricing=False)
        session.add(store)
        await session.flush()
        product = Product(store_id=1, name="Pneu", price=90, stock_qty=100, category="tires")
        session.add(product)
        await session.commit()


@pytest.mark.parametrize("role", ["manager", "admin"])
def test_b2b_routes_happy_path(role: str) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _prepare():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await _seed_db(Session)

    asyncio.run(_prepare())
    app = _build_app(Session, role=role)
    client = TestClient(app)

    with patch("security_overlay.guard.get_billing_snapshot", AsyncMock(return_value=BillingSnapshot(store_id=1, plan_code="gold", is_active=True))):
        account = client.post(
            "/b2b/accounts",
            json={"account_type": "garage", "name": "Garage Route", "payment_terms_days": 30},
        )
        assert account.status_code == 200
        account_id = account.json()["id"]

        contact = client.post(
            f"/b2b/accounts/{account_id}/users",
            json={"full_name": "Buyer One", "email": "buyer@example.com", "role": "buyer"},
        )
        assert contact.status_code == 200

        pricing = client.post(
            f"/b2b/accounts/{account_id}/pricing",
            json={"rule_type": "discount", "product_id": 1, "discount_percent": 12.5, "currency": "EUR"},
        )
        assert pricing.status_code == 200

        quote = client.post(
            "/b2b/pricing/quote",
            json={"company_account_id": account_id, "product_id": 1, "qty": 2, "base_unit_price": 90},
        )
        assert quote.status_code == 200
        assert quote.json()["final_unit_price"] < 90

        order = client.post(
            "/b2b/orders",
            json={
                "company_account_id": account_id,
                "po_number": "PO-1",
                "currency": "EUR",
                "items": [{"product_id": 1, "name": "Pneu", "qty": 2}],
                "auto_approve": role == "admin",
            },
        )
        assert order.status_code == 200
        order_payload = order.json()
        assert order_payload["company_account_id"] == account_id

        if role == "admin":
            invoice = client.post(
                "/b2b/invoices/grouped",
                json={"company_account_id": account_id, "order_ids": [order_payload["id"]], "payment_mode": "deferred"},
            )
            assert invoice.status_code == 200
            assert invoice.json()["grouped_order_ids"] == [order_payload["id"]]
        else:
            approve = client.post(f"/b2b/orders/{order_payload['id']}/approve")
            assert approve.status_code == 403

        dashboard = client.get("/b2b/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["accounts_total"] >= 1

    asyncio.run(engine.dispose())
