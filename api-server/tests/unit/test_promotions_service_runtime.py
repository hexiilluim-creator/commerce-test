

import pytest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.promotions_service import (
    PromotionContext, _normalize_country, _normalize_code, _normalize_many,
    _to_decimal, _q4, build_promotion_context,
)


def test_promotion_normalizers_and_context_properties():
    assert _normalize_country(" tn-extra") == "TN"
    assert _normalize_country("") is None
    assert _normalize_code(" cp10 ") == "CP10"
    assert _normalize_many([" A ", "", "b"]) == {"a", "b"}
    assert _to_decimal("bad", "2") == Decimal("2")
    assert _q4(Decimal("1.23456")) == Decimal("1.2346")
    context = PromotionContext(1, [], Decimal("0"), __import__("datetime").datetime.now(), order_count=3)
    assert context.is_loyal_customer and not context.is_new_customer


@pytest.mark.asyncio
async def test_build_promotion_context_without_db_normalizes_items_and_event():
    result = await build_promotion_context(None, store_id=4, items=[
        {"qty": 2, "unit_price": "3.3333", "category": " Brake ", "product_id": 9, "brand": " Bosch "},
    ], country_code=" tn ", channel=" WhatsApp ", customer_phone="p", event_context={"lead_label": " Hot ", "lead_score": 80, "trigger_type": " CART "})
    assert result.subtotal == Decimal("6.6666")
    assert result.total_quantity == 2 and result.categories == {"brake"} and result.product_ids == {9}
    assert result.country_code == "TN" and result.channel == "whatsapp" and result.lead_label == "hot"


@pytest.mark.asyncio
async def test_build_promotion_context_resolves_customer_and_order_history():
    customer = SimpleNamespace(id=12)
    db = MagicMock()
    db.get = AsyncMock(return_value=customer)
    count_result = MagicMock(); count_result.scalar.return_value = 3
    date_result = MagicMock(); date_result.scalar.return_value = None
    db.execute = AsyncMock(side_effect=[count_result, date_result])
    result = await build_promotion_context(db, store_id=4, items=[], customer_id=12)
    assert result.customer_id == 12 and result.order_count == 3 and result.is_loyal_customer


from services.promotions_service import (
    _matches_condition, _time_window_matches, _eligible_item_indexes,
    _promotion_conditions, _line_total, _ensure_adjustments,
)


def test_promotion_conditions_cover_customer_segments_and_windows():
    now = __import__("datetime").datetime(2026, 8, 14, 10, 30)
    ctx = PromotionContext(1, [{"product_id": 3}], Decimal("120"), now, country_code="TN", channel="whatsapp", customer_id=7, customer_email="A@x", customer_phone="p", order_count=3, total_quantity=2, categories={"brake"}, product_ids={3}, brands={"bosch"}, lead_label="hot", trigger_type="cart", days_since_last_order=10)
    checks = {
        "minimum_cart_amount": 100, "product_ids": [3], "categories": ["BRAKE"], "brands": ["BOSCH"],
        "country_codes": ["TN"], "channels": ["whatsapp"], "min_quantity": 2, "loyal_customer": True,
        "customer_segment": "hot", "lead_labels": ["hot"], "trigger_types": ["cart"], "inactivity_days_gte": 7,
        "customer_emails": ["a@x"], "customer_phones": ["p"], "hours": {"start": "09:00", "end": "12:00"},
    }
    assert all(_matches_condition(k, v, ctx) for k, v in checks.items())
    assert _time_window_matches({"start": "22:00", "end": "23:00"}, now) is False
    assert _matches_condition("unknown", None, ctx) is True


def test_promotion_item_targeting_adjustments_and_implicit_conditions():
    items = [{"product_id": 1, "category": "brake", "brand": "Bosch", "qty": 2, "unit_price": "3.25"}, {"product_id": 2, "is_promotional_gift": True}]
    assert _eligible_item_indexes(items, SimpleNamespace(applies_to="all")) == [0]
    assert _eligible_item_indexes(items, SimpleNamespace(applies_to="products", eligible_product_ids=[1], eligible_categories=None, eligible_brands=None)) == [0]
    assert _eligible_item_indexes(items, SimpleNamespace(applies_to="categories", eligible_product_ids=None, eligible_categories=["brake"], eligible_brands=None)) == [0]
    assert _eligible_item_indexes(items, SimpleNamespace(applies_to="brands", eligible_product_ids=None, eligible_categories=None, eligible_brands=["bosch"])) == [0]
    assert _line_total(items[0]) == Decimal("6.5000")
    adjusted = {}; assert _ensure_adjustments(adjusted) == [] and "original_unit_price" in adjusted
    promotion = SimpleNamespace(applies_to="products", eligible_product_ids=[1], eligible_categories=None, eligible_brands=None, country_codes=["TN"], channel_codes=["whatsapp"], customer_segment="new")
    assert _promotion_conditions(promotion, "cart") == [{"product_ids": [1], "country_codes": ["TN"], "channels": ["whatsapp"], "customer_segment": "new", "trigger_types": ["cart"]}]
