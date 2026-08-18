from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
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
from services.tax_service import calculate_manual_amount_taxes, calculate_taxes_for_items, migrate_legacy_tax_data


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
