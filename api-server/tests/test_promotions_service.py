from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

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

from models.database import Base, Coupon, Product, Promotion, PromotionRule, Store
from services.promotions_service import apply_promotions_to_items, preview_product_promo_price


@pytest.mark.asyncio
async def test_preview_product_promo_price_applies_automatic_category_discount() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        store = Store(name="AC", slug="ac", default_tax_country="FR", country="FR")
        session.add(store)
        await session.flush()

        product = Product(store_id=store.id, name="Pneu premium", price=100, stock_qty=10, category="tires")
        session.add(product)
        await session.flush()

        promotion = Promotion(
            store_id=store.id,
            name="-10% pneus",
            promotion_type="automatic",
            discount_type="percentage",
            discount_value=10,
            applies_to="categories",
            eligible_categories=["tires"],
            channel_codes=["storefront"],
            is_active=True,
        )
        session.add(promotion)
        await session.commit()

        promo_price = await preview_product_promo_price(session, store=store, product=product, channel="storefront")
        assert promo_price == pytest.approx(90.0, abs=0.01)

    await engine.dispose()


@pytest.mark.asyncio
async def test_apply_promotions_to_items_supports_coupon_and_min_cart_rule() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        store = Store(name="AC", slug="ac2", default_tax_country="FR", country="FR")
        session.add(store)
        await session.flush()

        promotion = Promotion(
            store_id=store.id,
            name="SAVE15",
            promotion_type="coupon",
            discount_type="fixed",
            discount_value=15,
            applies_to="all",
            is_active=True,
            stackable=False,
        )
        session.add(promotion)
        await session.flush()
        session.add(PromotionRule(
            store_id=store.id,
            promotion_id=promotion.id,
            conditions={"minimum_cart_amount": 50, "country_codes": ["FR"]},
        ))
        session.add(Coupon(
            store_id=store.id,
            promotion_id=promotion.id,
            code="SAVE15",
            coupon_kind="multi",
            per_customer_limit=1,
        ))
        await session.commit()

        result = await apply_promotions_to_items(
            session,
            store=store,
            items=[
                {"name": "Produit A", "qty": 1, "unit_price": 40, "category": "parts"},
                {"name": "Produit B", "qty": 1, "unit_price": 20, "category": "parts"},
            ],
            coupon_codes=["save15"],
            country_code="FR",
            channel="storefront",
        )

        assert float(result.discount_amount) == pytest.approx(15.0, abs=0.01)
        assert result.applied_coupon_codes == ["SAVE15"]
        final_total = sum(float(item["unit_price"]) * int(item.get("qty", 1)) for item in result.items)
        assert final_total == pytest.approx(45.0, abs=0.02)
        assert result.applied_promotions[0]["promotion_name"] == "SAVE15"

    await engine.dispose()
