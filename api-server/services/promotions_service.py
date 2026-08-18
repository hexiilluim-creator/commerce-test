from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import Coupon, Customer, Order, Product, Promotion, PromotionRule, PromotionUsage, Store

_DECIMAL_4 = Decimal("0.0001")


@dataclass(slots=True)
class PromotionContext:
    store_id: int
    items: list[dict[str, Any]]
    subtotal: Decimal
    now: datetime
    country_code: str | None = None
    channel: str | None = None
    customer_id: int | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    customer_name: str | None = None
    order_count: int = 0
    total_quantity: int = 0
    categories: set[str] | None = None
    product_ids: set[int] | None = None
    brands: set[str] | None = None
    lead_label: str | None = None
    lead_score: int | None = None
    trigger_type: str | None = None
    days_since_last_order: int | None = None

    @property
    def is_new_customer(self) -> bool:
        return self.order_count == 0

    @property
    def is_loyal_customer(self) -> bool:
        return self.order_count >= 3


@dataclass(slots=True)
class PromotionApplicationResult:
    items: list[dict[str, Any]]
    discount_amount: Decimal
    applied_promotions: list[dict[str, Any]]
    applied_coupon_codes: list[str]



def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return Decimal(default)



def _q4(value: Decimal) -> Decimal:
    return value.quantize(_DECIMAL_4, rounding=ROUND_HALF_UP)



def _normalize_country(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().upper()[:2]
    return cleaned or None



def _normalize_code(value: str) -> str:
    return value.strip().upper()



def _normalize_many(values: list[str] | None) -> set[str]:
    return {str(v).strip().lower() for v in (values or []) if str(v).strip()}


async def _resolve_customer(db: AsyncSession | None, *, store_id: int, customer_id: int | None, customer_phone: str | None) -> Customer | None:
    if db is None:
        return None
    if customer_id:
        return await db.get(Customer, customer_id)
    if customer_phone:
        result = await db.execute(
            select(Customer).where(Customer.store_id == store_id, Customer.whatsapp_phone == customer_phone)
        )
        return result.scalar_one_or_none()
    return None


async def build_promotion_context(
    db: AsyncSession | None,
    *,
    store_id: int,
    items: list[dict[str, Any]],
    country_code: str | None = None,
    channel: str | None = None,
    customer_id: int | None = None,
    customer_email: str | None = None,
    customer_phone: str | None = None,
    customer_name: str | None = None,
    event_context: dict[str, Any] | None = None
) -> PromotionContext:
    now = datetime.now(UTC)
    subtotal = _q4(sum((_to_decimal(item.get("qty", 1), "1") * _to_decimal(item.get("unit_price", 0)) for item in items), start=Decimal("0")))
    categories = {
        str(item.get("category") or item.get("tax_category") or "").strip().lower()
        for item in items
        if str(item.get("category") or item.get("tax_category") or "").strip()
    }
    product_ids = {
        int(item.get("product_id"))
        for item in items
        if item.get("product_id") is not None
    }
    brands = {
        str(item.get("brand") or "").strip().lower()
        for item in items
        if str(item.get("brand") or "").strip()
    }
    total_quantity = int(sum(int(item.get("qty", 1) or 1) for item in items))

    customer = await _resolve_customer(db, store_id=store_id, customer_id=customer_id, customer_phone=customer_phone)
    resolved_customer_id = customer_id or getattr(customer, "id", None)
    order_count = 0
    lead_label = event_context.get("lead_label") if event_context else None
    lead_score = event_context.get("lead_score") if event_context else None
    days_since_last_order = event_context.get("days_since_last_order") if event_context else None

    if db is not None and resolved_customer_id:
        count_stmt = select(func.count()).select_from(Order).where(
            Order.store_id == store_id,
            Order.customer_id == resolved_customer_id
        )
        order_count = int((await db.execute(count_stmt)).scalar() or 0)
        max_dt_stmt = select(func.max(Order.created_at)).where(
            Order.store_id == store_id,
            Order.customer_id == resolved_customer_id
        )
        last_order_at = (await db.execute(max_dt_stmt)).scalar()
        if last_order_at is not None and days_since_last_order is None:
            delta = now - last_order_at
            days_since_last_order = max(0, int(delta.total_seconds() // 86400))

    return PromotionContext(
        store_id=store_id,
        items=items,
        subtotal=subtotal,
        now=now,
        country_code=_normalize_country(country_code),
        channel=(channel or "").strip().lower() or None,
        customer_id=resolved_customer_id,
        customer_email=customer_email,
        customer_phone=customer_phone,
        customer_name=customer_name,
        order_count=order_count,
        total_quantity=total_quantity,
        categories=categories,
        product_ids=product_ids,
        brands=brands,
        lead_label=(lead_label or "").strip().lower() or None,
        lead_score=lead_score,
        trigger_type=((event_context or {}).get("trigger_type") or "").strip().lower() or None,
        days_since_last_order=days_since_last_order
    )


async def _load_rules(db: AsyncSession | None, promotion_ids: list[int]) -> dict[int, list[PromotionRule]]:
    if db is None or not promotion_ids:
        return {}
    result = await db.execute(
        select(PromotionRule)
        .where(PromotionRule.promotion_id.in_(promotion_ids), PromotionRule.is_active.is_(True))
        .order_by(PromotionRule.priority.asc(), PromotionRule.id.asc())
    )
    grouped: dict[int, list[PromotionRule]] = {}
    for row in result.scalars().all():
        grouped.setdefault(int(row.promotion_id), []).append(row)
    return grouped


async def _fetch_candidate_promotions(
    db: AsyncSession | None,
    *,
    store_id: int,
    now: datetime,
    coupon_codes: list[str],
    allowed_promotion_types: set[str] | None = None
) -> tuple[list[Promotion], dict[str, Coupon]]:
    if db is None:
        return [], {}

    stmt = (
        select(Promotion)
        .where(
            Promotion.store_id == store_id,
            Promotion.is_active.is_(True),
            or_(Promotion.start_at.is_(None), Promotion.start_at <= now),
            or_(Promotion.end_at.is_(None), Promotion.end_at >= now)
        )
        .order_by(Promotion.priority.asc(), Promotion.id.asc())
    )
    result = await db.execute(stmt)
    promotions = result.scalars().all()
    if allowed_promotion_types:
        promotions = [p for p in promotions if (p.promotion_type or "automatic") in allowed_promotion_types]

    coupon_map: dict[str, Coupon] = {}
    if coupon_codes:
        coupon_result = await db.execute(
            select(Coupon).where(
                Coupon.store_id == store_id,
                Coupon.code.in_(coupon_codes),
                Coupon.is_active.is_(True),
                or_(Coupon.starts_at.is_(None), Coupon.starts_at <= now),
                or_(Coupon.ends_at.is_(None), Coupon.ends_at >= now)
            )
        )
        for coupon in coupon_result.scalars().all():
            coupon_map[_normalize_code(coupon.code)] = coupon
    return promotions, coupon_map


async def _count_usage(
    db: AsyncSession | None,
    *,
    store_id: int,
    promotion_id: int | None = None,
    coupon_id: int | None = None,
    customer_id: int | None = None,
    customer_email: str | None = None,
    customer_phone: str | None = None
) -> int:
    if db is None:
        return 0
    stmt = select(func.count()).select_from(PromotionUsage).where(PromotionUsage.store_id == store_id)
    if promotion_id is not None:
        stmt = stmt.where(PromotionUsage.promotion_id == promotion_id)
    if coupon_id is not None:
        stmt = stmt.where(PromotionUsage.coupon_id == coupon_id)
    if customer_id is not None:
        stmt = stmt.where(PromotionUsage.customer_id == customer_id)
    elif customer_email or customer_phone:
        branches = []
        if customer_email:
            branches.append(PromotionUsage.customer_email == customer_email)
        if customer_phone:
            branches.append(PromotionUsage.customer_phone == customer_phone)
        stmt = stmt.where(or_(*branches))
    return int((await db.execute(stmt)).scalar() or 0)



def _time_window_matches(raw: Any, now: datetime) -> bool:
    if not raw:
        return True
    if isinstance(raw, list):
        current_hour = now.hour
        return current_hour in {int(v) for v in raw}
    if isinstance(raw, dict):
        start_raw = str(raw.get("start") or "00:00")
        end_raw = str(raw.get("end") or "23:59")
        start = time.fromisoformat(start_raw)
        end = time.fromisoformat(end_raw)
        now_t = now.timetz().replace(tzinfo=None)
        return start <= now_t <= end
    return True



def _matches_condition(condition_key: str, expected: Any, context: PromotionContext) -> bool:
    if condition_key == "minimum_cart_amount":
        return context.subtotal >= _to_decimal(expected)
    if condition_key == "product_ids":
        wanted = {int(v) for v in (expected or [])}
        return bool(wanted & (context.product_ids or set()))
    if condition_key == "categories":
        wanted = _normalize_many(expected)
        return bool(wanted & (context.categories or set()))
    if condition_key == "brands":
        wanted = _normalize_many(expected)
        return bool(wanted & (context.brands or set()))
    if condition_key in {"country_codes", "countries", "zone"}:
        wanted = {str(v).strip().upper() for v in (expected or [])}
        return not wanted or (context.country_code in wanted)
    if condition_key in {"channels", "channel"}:
        wanted = _normalize_many(expected if isinstance(expected, list) else [expected])
        return not wanted or (context.channel in wanted)
    if condition_key in {"min_quantity", "min_total_quantity"}:
        return context.total_quantity >= int(expected)
    if condition_key == "new_customer":
        return bool(expected) == context.is_new_customer
    if condition_key == "loyal_customer":
        return bool(expected) == context.is_loyal_customer
    if condition_key == "customer_segment":
        raw = str(expected or "").strip().lower()
        if raw == "new":
            return context.is_new_customer
        if raw == "loyal":
            return context.is_loyal_customer
        if raw in {"cold", "warm", "hot"}:
            return context.lead_label == raw
        return True
    if condition_key == "lead_labels":
        return context.lead_label in _normalize_many(expected)
    if condition_key == "trigger_types":
        wanted = _normalize_many(expected)
        return bool(context.trigger_type and context.trigger_type in wanted)
    if condition_key == "first_purchase":
        return bool(expected) == context.is_new_customer
    if condition_key == "inactivity_days_gte":
        return context.days_since_last_order is not None and context.days_since_last_order >= int(expected)
    if condition_key == "customer_emails":
        wanted = {str(v).strip().lower() for v in (expected or [])}
        return bool(context.customer_email and context.customer_email.lower() in wanted)
    if condition_key == "customer_phones":
        wanted = {str(v).strip() for v in (expected or [])}
        return bool(context.customer_phone and context.customer_phone in wanted)
    if condition_key == "hours":
        return _time_window_matches(expected, context.now)
    return True



def _promotion_conditions(promotion: Promotion, campaign_trigger_type: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    implicit: dict[str, Any] = {}
    if promotion.applies_to == "products" and promotion.eligible_product_ids:
        implicit["product_ids"] = promotion.eligible_product_ids
    if promotion.applies_to == "categories" and promotion.eligible_categories:
        implicit["categories"] = promotion.eligible_categories
    if promotion.applies_to == "brands" and promotion.eligible_brands:
        implicit["brands"] = promotion.eligible_brands
    if promotion.country_codes:
        implicit["country_codes"] = promotion.country_codes
    if promotion.channel_codes:
        implicit["channels"] = promotion.channel_codes
    if promotion.customer_segment:
        implicit["customer_segment"] = promotion.customer_segment
    if campaign_trigger_type:
        implicit["trigger_types"] = [campaign_trigger_type]
    if implicit:
        out.append(implicit)
    return out


async def _campaign_trigger_map(db: AsyncSession | None, promotions: list[Promotion]) -> dict[int, str | None]:
    if db is None:
        return {}
    campaign_ids = sorted({int(p.campaign_id) for p in promotions if p.campaign_id is not None})
    if not campaign_ids:
        return {}
    from models.database import Campaign

    result = await db.execute(select(Campaign.id, Campaign.trigger_type).where(Campaign.id.in_(campaign_ids)))
    return {int(row[0]): row[1] for row in result.all()}


async def _promotion_is_eligible(
    db: AsyncSession | None,
    *,
    promotion: Promotion,
    coupon: Coupon | None,
    rules: list[PromotionRule],
    context: PromotionContext,
    campaign_trigger_type: str | None
) -> bool:
    if coupon is None and (promotion.promotion_type or "automatic") == "coupon":
        return False
    if coupon is not None and coupon.promotion_id not in (None, promotion.id):
        return False

    if promotion.max_global_uses is not None:
        global_uses = await _count_usage(db, store_id=context.store_id, promotion_id=promotion.id)
        if global_uses >= int(promotion.max_global_uses):
            return False

    per_customer_limit = promotion.max_uses_per_customer
    if coupon is not None and coupon.per_customer_limit is not None:
        per_customer_limit = coupon.per_customer_limit
    if per_customer_limit is not None:
        customer_uses = await _count_usage(
            db,
            store_id=context.store_id,
            promotion_id=promotion.id,
            coupon_id=getattr(coupon, "id", None),
            customer_id=context.customer_id,
            customer_email=context.customer_email,
            customer_phone=context.customer_phone
        )
        if customer_uses >= int(per_customer_limit):
            return False

    if coupon is not None and coupon.max_redemptions is not None:
        if int(coupon.redemptions_count or 0) >= int(coupon.max_redemptions):
            return False

    all_conditions = _promotion_conditions(promotion, campaign_trigger_type=campaign_trigger_type)
    all_conditions.extend(rule.conditions or {} for rule in rules if rule.conditions)
    return all(_matches_condition(key, value, context) for cond in all_conditions for key, value in cond.items())



def _eligible_item_indexes(items: list[dict[str, Any]], promotion: Promotion) -> list[int]:
    if promotion.applies_to == "all":
        return [idx for idx, item in enumerate(items) if not item.get("is_promotional_gift")]

    wanted_products = {int(v) for v in (promotion.eligible_product_ids or [])}
    wanted_categories = _normalize_many(promotion.eligible_categories)
    wanted_brands = _normalize_many(promotion.eligible_brands)

    eligible: list[int] = []
    for idx, item in enumerate(items):
        if item.get("is_promotional_gift"):
            continue
        pid = item.get("product_id")
        category = str(item.get("category") or item.get("tax_category") or "").strip().lower()
        brand = str(item.get("brand") or "").strip().lower()
        if promotion.applies_to == "products" and pid in wanted_products:
            eligible.append(idx)
        elif promotion.applies_to == "categories" and category and category in wanted_categories:
            eligible.append(idx)
        elif promotion.applies_to == "brands" and brand and brand in wanted_brands:
            eligible.append(idx)
    return eligible



def _line_total(item: dict[str, Any]) -> Decimal:
    return _q4(_to_decimal(item.get("unit_price", 0)) * _to_decimal(item.get("qty", 1), "1"))



def _ensure_adjustments(item: dict[str, Any]) -> list[dict[str, Any]]:
    adjustments = item.setdefault("promotion_adjustments", [])
    if "original_unit_price" not in item:
        item["original_unit_price"] = item.get("unit_price")
    return adjustments


async def _apply_promotion_to_items(
    db: AsyncSession | None,
    *,
    promotion: Promotion,
    coupon: Coupon | None,
    items: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], Decimal, dict[str, Any] | None]:
    working = deepcopy(items)
    eligible_indexes = _eligible_item_indexes(working, promotion)
    if not eligible_indexes and promotion.discount_type != "gift":
        return items, Decimal("0"), None

    total_discount = Decimal("0")
    details: dict[str, Any] = {
        "promotion_id": promotion.id,
        "promotion_name": promotion.name,
        "discount_type": promotion.discount_type,
        "coupon_id": getattr(coupon, "id", None),
        "coupon_code": getattr(coupon, "code", None),
        "discount_amount": 0.0,
        "gift": None,
    }

    if promotion.discount_type == "percentage":
        rate = _to_decimal(promotion.discount_value) / Decimal("100")
        max_discount = _to_decimal(promotion.max_discount_amount) if promotion.max_discount_amount is not None else None
        for idx in eligible_indexes:
            item = working[idx]
            qty = _to_decimal(item.get("qty", 1), "1")
            current_unit = _to_decimal(item.get("unit_price", 0))
            line_total = _q4(current_unit * qty)
            line_discount = _q4(line_total * rate)
            if max_discount is not None:
                remaining_cap = max(Decimal("0"), _q4(max_discount - total_discount))
                line_discount = min(line_discount, remaining_cap)
            if line_discount <= 0:
                continue
            new_line_total = max(Decimal("0"), _q4(line_total - line_discount))
            new_unit = Decimal("0") if qty == 0 else _q4(new_line_total / qty)
            item["unit_price"] = float(new_unit)
            _ensure_adjustments(item).append({
                "promotion_id": promotion.id,
                "promotion_name": promotion.name,
                "discount_type": promotion.discount_type,
                "discount_amount": float(line_discount),
            })
            total_discount = _q4(total_discount + line_discount)
    elif promotion.discount_type == "fixed":
        fixed_value = _to_decimal(promotion.discount_value)
        eligible_totals = [(_line_total(working[idx]), idx) for idx in eligible_indexes]
        eligible_sum = _q4(sum((line_total for line_total, _ in eligible_totals), start=Decimal("0")))
        fixed_value = min(fixed_value, eligible_sum)
        remaining = fixed_value
        for pos, (line_total, idx) in enumerate(eligible_totals):
            item = working[idx]
            qty = _to_decimal(item.get("qty", 1), "1")
            if pos == len(eligible_totals) - 1:
                line_discount = remaining
            else:
                share = Decimal("0") if eligible_sum == 0 else _q4((line_total / eligible_sum) * fixed_value)
                line_discount = min(share, remaining, line_total)
            line_discount = min(line_discount, line_total)
            new_line_total = max(Decimal("0"), _q4(line_total - line_discount))
            new_unit = Decimal("0") if qty == 0 else _q4(new_line_total / qty)
            item["unit_price"] = float(new_unit)
            _ensure_adjustments(item).append({
                "promotion_id": promotion.id,
                "promotion_name": promotion.name,
                "discount_type": promotion.discount_type,
                "discount_amount": float(line_discount),
            })
            total_discount = _q4(total_discount + line_discount)
            remaining = max(Decimal("0"), _q4(remaining - line_discount))
    elif promotion.discount_type == "gift":
        gift_item: dict[str, Any] | None = None
        if promotion.gift_product_id and db is not None:
            product = await db.get(Product, int(promotion.gift_product_id))
            if product is not None:
                gift_item = {
                    "product_id": product.id,
                    "name": product.name,
                    "qty": int(promotion.gift_quantity or 1),
                    "unit_price": 0.0,
                    "category": product.category,
                    "tax_category": product.tax_category,
                    "is_tax_exempt": True,
                    "is_promotional_gift": True,
                }
        if gift_item is None:
            gift_item = {
                "product_id": None,
                "name": promotion.gift_name or "Cadeau offert",
                "qty": int(promotion.gift_quantity or 1),
                "unit_price": 0.0,
                "category": "gift",
                "tax_category": "gift",
                "is_tax_exempt": True,
                "is_promotional_gift": True,
            }
        working.append(gift_item)
        details["gift"] = {
            "name": gift_item["name"],
            "qty": gift_item["qty"],
        }
    elif promotion.discount_type == "free_shipping":
        details["free_shipping"] = True
    else:
        return items, Decimal("0"), None

    details["discount_amount"] = float(total_discount)
    return working, total_discount, details


async def apply_promotions_to_items(
    db: AsyncSession | None,
    *,
    store: Store,
    items: list[dict[str, Any]],
    coupon_codes: list[str] | None = None,
    country_code: str | None = None,
    channel: str | None = None,
    customer_id: int | None = None,
    customer_email: str | None = None,
    customer_phone: str | None = None,
    customer_name: str | None = None,
    event_context: dict[str, Any] | None = None,
    allowed_promotion_types: set[str] | None = None
) -> PromotionApplicationResult:
    normalized_codes = [_normalize_code(code) for code in (coupon_codes or []) if str(code).strip()]
    context = await build_promotion_context(
        db,
        store_id=store.id,
        items=items,
        country_code=country_code,
        channel=channel,
        customer_id=customer_id,
        customer_email=customer_email,
        customer_phone=customer_phone,
        customer_name=customer_name,
        event_context=event_context
    )
    promotions, coupon_map = await _fetch_candidate_promotions(
        db,
        store_id=store.id,
        now=context.now,
        coupon_codes=normalized_codes,
        allowed_promotion_types=allowed_promotion_types
    )
    rule_map = await _load_rules(db, [int(p.id) for p in promotions])
    campaign_trigger_map = await _campaign_trigger_map(db, promotions)

    promotion_by_id = {int(p.id): p for p in promotions}
    ordered_candidates: list[tuple[Promotion, Coupon | None]] = []

    for promo in promotions:
        ptype = promo.promotion_type or "automatic"
        if ptype in {"automatic", "smart"}:
            ordered_candidates.append((promo, None))

    for code in normalized_codes:
        coupon = coupon_map.get(code)
        if not coupon:
            continue
        if coupon.promotion_id is not None and int(coupon.promotion_id) in promotion_by_id:
            ordered_candidates.append((promotion_by_id[int(coupon.promotion_id)], coupon))

    working_items = deepcopy(items)
    total_discount = Decimal("0")
    applied_promotions: list[dict[str, Any]] = []
    applied_codes: list[str] = []
    has_non_stackable = False

    for promotion, coupon in ordered_candidates:
        if has_non_stackable:
            break
        rules = rule_map.get(int(promotion.id), [])
        is_eligible = await _promotion_is_eligible(
            db,
            promotion=promotion,
            coupon=coupon,
            rules=rules,
            context=context,
            campaign_trigger_type=campaign_trigger_map.get(int(promotion.campaign_id)) if promotion.campaign_id else None
        )
        if not is_eligible:
            continue

        updated_items, discount_amount, details = await _apply_promotion_to_items(
            db,
            promotion=promotion,
            coupon=coupon,
            items=working_items
        )
        if details is None:
            continue
        working_items = updated_items
        total_discount = _q4(total_discount + discount_amount)
        applied_promotions.append(details)
        if coupon is not None:
            applied_codes.append(_normalize_code(coupon.code))
        if not bool(promotion.stackable):
            has_non_stackable = True

    return PromotionApplicationResult(
        items=working_items,
        discount_amount=total_discount,
        applied_promotions=applied_promotions,
        applied_coupon_codes=applied_codes
    )


async def record_promotion_usage(
    db: AsyncSession | None,
    *,
    store_id: int,
    applied_promotions: list[dict[str, Any]],
    customer_id: int | None = None,
    customer_email: str | None = None,
    customer_phone: str | None = None,
    order_id: int | None = None,
    payment_link_id: int | None = None
) -> None:
    if db is None:
        return
    for applied in applied_promotions:
        usage = PromotionUsage(
            store_id=store_id,
            promotion_id=applied.get("promotion_id"),
            coupon_id=applied.get("coupon_id"),
            customer_id=customer_id,
            customer_email=customer_email,
            customer_phone=customer_phone,
            order_id=order_id,
            payment_link_id=payment_link_id,
            discount_amount=_to_decimal(applied.get("discount_amount", 0)),
            details=applied
        )
        db.add(usage)
        if applied.get("coupon_id"):
            coupon = await db.get(Coupon, int(applied["coupon_id"]))
            if coupon is not None:
                coupon.redemptions_count = int(coupon.redemptions_count or 0) + 1


async def preview_product_promo_price(
    db: AsyncSession | None,
    *,
    store: Store,
    product: Product,
    country_code: str | None = None,
    channel: str | None = "storefront"
) -> float | None:
    base_item = {
        "product_id": product.id,
        "name": product.name,
        "qty": 1,
        "unit_price": float(product.price),
        "category": product.category,
        "tax_category": product.tax_category,
    }
    result = await apply_promotions_to_items(
        db,
        store=store,
        items=[base_item],
        country_code=country_code,
        channel=channel,
        allowed_promotion_types={"automatic"}
    )
    if not result.applied_promotions:
        return None
    discounted = result.items[0]
    return float(discounted.get("unit_price", product.price))


async def generate_smart_recommendations(
    db: AsyncSession | None,
    *,
    store: Store,
    customer_id: int | None = None,
    customer_email: str | None = None,
    customer_phone: str | None = None,
    channel: str | None = None,
    country_code: str | None = None,
    trigger_type: str | None = None
) -> list[dict[str, Any]]:
    context = await build_promotion_context(
        db,
        store_id=store.id,
        items=[],
        customer_id=customer_id,
        customer_email=customer_email,
        customer_phone=customer_phone,
        channel=channel,
        country_code=country_code,
        event_context={"trigger_type": trigger_type} if trigger_type else None
    )
    promotions, _ = await _fetch_candidate_promotions(
        db,
        store_id=store.id,
        now=context.now,
        coupon_codes=[],
        allowed_promotion_types={"smart", "automatic"}
    )
    rule_map = await _load_rules(db, [int(p.id) for p in promotions])
    campaign_trigger_map = await _campaign_trigger_map(db, promotions)

    recommendations: list[dict[str, Any]] = []
    for promotion in promotions:
        if not await _promotion_is_eligible(
            db,
            promotion=promotion,
            coupon=None,
            rules=rule_map.get(int(promotion.id), []),
            context=context,
            campaign_trigger_type=campaign_trigger_map.get(int(promotion.campaign_id)) if promotion.campaign_id else None
        ):
            continue
        recommendations.append(
            {
                "promotion_id": promotion.id,
                "name": promotion.name,
                "description": promotion.description,
                "promotion_type": promotion.promotion_type,
                "discount_type": promotion.discount_type,
                "discount_value": float(promotion.discount_value) if promotion.discount_value is not None else None,
                "trigger_type": campaign_trigger_map.get(int(promotion.campaign_id)) if promotion.campaign_id else None,
                "priority": promotion.priority,
                "customer_segment": promotion.customer_segment,
            }
        )
    return recommendations
