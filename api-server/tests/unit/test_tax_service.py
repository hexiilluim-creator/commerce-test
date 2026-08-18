from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-chars-minimum-ok!")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test-app-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test-verify-token")
os.environ.setdefault("INSTAGRAM_VERIFY_TOKEN", "test-ig-token")
os.environ.setdefault("FACEBOOK_VERIFY_TOKEN", "test-fb-token")
os.environ.setdefault("TIKTOK_VERIFY_TOKEN", "test-tt-token")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-000000000000000000000000000000000000000000000000")
os.environ.setdefault("DEEPSEEK_API_KEY", "ds-test-000000000000000000000000")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token-001")
os.environ.setdefault("SERVER_DOMAIN", "https://test.example.com")

from models.database import Base, Store, TaxExemption, TaxRate
from services.tax_service import (
    calculate_manual_amount_taxes,
    calculate_order_taxes,
    calculate_taxes_for_items,
    enrich_order_items_with_product_tax_data,
    migrate_legacy_tax_data,
)


@pytest.mark.asyncio
async def test_tax_service_applies_store_country_category_rate_history() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        store = Store(name="AC", slug="ac", default_tax_country="FR", country="FR")
        session.add(store)
        await session.flush()
        session.add_all([
            TaxRate(store_id=store.id, country_code="FR", product_category="services", rate=0.20, valid_from=date(2020, 1, 1), priority=100, name="TVA"),
            TaxRate(store_id=store.id, country_code="FR", product_category="services", rate=0.10, valid_from=date(2030, 1, 1), priority=100, name="TVA réduite future"),
        ])
        await session.commit()

        result = await calculate_taxes_for_items(
            db=session,
            store=store,
            items=[{"name": "Consulting", "qty": 1, "unit_price": 120, "tax_category": "services"}],
            country_code="FR",
            prices_include_tax=True,
            as_of=datetime.now(UTC).date(),
        )

        assert float(result.total_amount) == pytest.approx(120.0)
        assert float(result.subtotal_amount) == pytest.approx(100.0, abs=0.01)
        assert float(result.tax_amount) == pytest.approx(20.0, abs=0.01)
        assert result.breakdown[0]["rate"] == pytest.approx(0.20)

    await engine.dispose()


@pytest.mark.asyncio
async def test_tax_service_supports_exemption_and_zero_tax() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        store = Store(name="AC", slug="ac2", default_tax_country="TN", country="TN")
        session.add(store)
        await session.flush()
        session.add(
            TaxExemption(
                store_id=store.id,
                customer_email="vip@example.com",
                reason="export B2B",
                valid_from=date(2020, 1, 1),
            )
        )
        await session.commit()

        result = await calculate_manual_amount_taxes(
            session,
            store=store,
            description="Export part",
            amount=100,
            country_code="TN",
            customer_email="vip@example.com",
            prices_include_tax=False,
        )
        assert float(result.tax_amount) == pytest.approx(0.0)
        assert float(result.total_amount) == pytest.approx(100.0)

    await engine.dispose()


@pytest.mark.asyncio
async def test_migrate_legacy_tax_data_backfills_orders_and_links() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from models.database import Customer, Order, PaymentLink

    async with Session() as session:
        store = Store(name="AC", slug="ac3", default_tax_country="TN", country="TN")
        session.add(store)
        await session.flush()
        customer = Customer(store_id=store.id, whatsapp_phone="+21612345678")
        session.add(customer)
        await session.flush()
        order = Order(
            store_id=store.id,
            customer_id=customer.id,
            items=[{"name": "Pièce", "qty": 1, "unit_price": 119}],
            total_amount=119,
        )
        link = PaymentLink(
            store_id=store.id,
            provider="cash",
            url=None,
            amount=119,
            currency="TND",
            description="Paiement",
            external_reference="legacy-1",
        )
        session.add_all([order, link])
        await session.commit()

        stats = await migrate_legacy_tax_data(session, store_id=store.id)
        assert stats["orders_updated"] == 1
        assert stats["payment_links_updated"] == 1

        await session.refresh(order)
        await session.refresh(link)
        assert order.tax_breakdown
        assert link.tax_breakdown
        assert float(order.tax_amount) >= 0
        assert float(link.tax_amount) >= 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_tax_service_fallback_country_and_prices_exclusive_tax():
    store = SimpleNamespace(default_tax_country="TN", country="TN", tax_inclusive_pricing=False, id=4)
    result = await calculate_taxes_for_items(
        db=None,
        store=store,
        items=[{"name": "Part", "quantity": 2, "price": "50", "category": " Parts "}],
        country_code=None,
        prices_include_tax=False,
    )
    assert result.country_code == "TN"
    assert result.items[0].category == "parts"
    assert result.subtotal_amount == Decimal("100.0000")
    assert result.tax_amount == Decimal("19.0000")
    assert result.total_amount == Decimal("119.0000")
    assert result.breakdown[0]["categories"] == ["parts"]


@pytest.mark.asyncio
async def test_tax_service_handles_zero_rate_country_and_item_exemption():
    store = SimpleNamespace(default_tax_country="AE", country="AE", tax_inclusive_pricing=True, id=5)
    result = await calculate_taxes_for_items(
        db=None,
        store=store,
        items=[
            {"product_name": "Zero", "qty": 1, "unit_price": 20},
            {"name": "Exempt", "qty": 1, "unit_price": 30, "is_tax_exempt": True},
        ],
        country_code=" ae ",
    )
    assert result.country_code == "AE"
    assert result.tax_amount == Decimal("0.0000")
    assert result.total_amount == Decimal("50.0000")
    assert result.items[1].exempt_reason == "product_marked_exempt"
    assert all(item.applied_rate == 0 for item in result.items)


@pytest.mark.asyncio
async def test_tax_computation_serializes_and_empty_items_cleanly():
    store = SimpleNamespace(default_tax_country=None, country=None, tax_inclusive_pricing=True, id=6)
    result = await calculate_taxes_for_items(db=None, store=store, items=[])
    payload = result.as_dict()
    assert payload["subtotal_amount"] == 0.0
    assert payload["tax_amount"] == 0.0 and payload["total_amount"] == 0.0
    assert payload["items"] == [] and payload["breakdown"] == []


@pytest.mark.asyncio
async def test_calculate_order_taxes_prefers_order_country_and_items():
    store = SimpleNamespace(default_tax_country="TN", country="TN", tax_inclusive_pricing=False, id=7)
    order = SimpleNamespace(items=[{"name": "Service", "qty": 1, "unit_price": 100}], country_code="US")
    result = await calculate_order_taxes(None, store=store, order=order, prices_include_tax=False)
    assert result.country_code == "US"
    assert result.tax_amount == Decimal("0.0000")
    assert result.total_amount == Decimal("100.0000")


@pytest.mark.asyncio
async def test_enrich_order_items_respects_tenant_and_preserves_existing_values():
    inside = SimpleNamespace(store_id=9, tax_category="parts", category="fallback", is_tax_exempt=True)
    outside = SimpleNamespace(store_id=10, tax_category="other", category="other", is_tax_exempt=False)
    db = SimpleNamespace(get=AsyncMock(side_effect=[inside, outside]))
    items = [
        {"product_id": 1, "name": "Inside"},
        {"product_id": 2, "name": "Outside"},
        {"product_id": None, "name": "Manual", "tax_category": "services", "is_tax_exempt": False},
    ]
    enriched = await enrich_order_items_with_product_tax_data(db, store_id=9, items=items)
    assert enriched[0]["tax_category"] == "parts" and enriched[0]["is_tax_exempt"] is True
    assert "tax_category" not in enriched[1] and "is_tax_exempt" not in enriched[1]
    assert enriched[2]["tax_category"] == "services"


@pytest.mark.asyncio
async def test_tax_rate_specific_rule_is_exempt_and_invalid_values_fallback():
    store = SimpleNamespace(default_tax_country="FR", country="FR", tax_inclusive_pricing=False, id=8)
    exempt_rate = SimpleNamespace(rate=Decimal("0"), name="Export", country_code="FR", product_category="services", is_exempt=True, is_zero_rate=True, legal_reference="VAT-EXEMPT")
    result_obj = SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: exempt_rate))
    db = SimpleNamespace(execute=AsyncMock(return_value=result_obj))
    result = await calculate_taxes_for_items(db=db, store=store, items=[{"name": "Export", "qty": "bad", "unit_price": "bad", "category": "services"}], country_code="FR")
    assert result.tax_amount == Decimal("0.0000") and result.items[0].exempt_reason == "VAT-EXEMPT"


@pytest.mark.asyncio
async def test_manual_amount_tax_uses_category_and_customer_phone():
    store = SimpleNamespace(default_tax_country="TN", country="TN", tax_inclusive_pricing=False, id=9)
    result = await calculate_manual_amount_taxes(None, store=store, description="Phone order", amount=Decimal("10.00"), customer_phone="+216123", category="Services", prices_include_tax=False)
    assert result.items[0].name == "Phone order"
    assert result.items[0].category == "services"
    assert result.tax_amount == Decimal("1.9000")
