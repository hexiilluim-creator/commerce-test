"""services/tax_service.py — moteur TVA multi-pays.

Couvre le Plan A / Bloc A1 :
- TVA par store
- TVA par pays
- TVA par catégorie produit
- TVA à 0 % / exonérations
- historique des taux
- migration/backfill des anciennes commandes et liens de paiement
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import Order, PaymentLink, Product, Store, TaxExemption, TaxRate

_DECIMAL_4 = Decimal("0.0001")
_DECIMAL_2 = Decimal("0.01")

DEFAULT_COUNTRY_VAT: dict[str, Decimal] = {
    "TN": Decimal("0.19"),
    "FR": Decimal("0.20"),
    "MA": Decimal("0.20"),
    "DZ": Decimal("0.19"),
    "AE": Decimal("0.00"),
    "SA": Decimal("0.15"),
    "EG": Decimal("0.14"),
    "GB": Decimal("0.20"),
    "US": Decimal("0.00"),
}


@dataclass(slots=True)
class AppliedTaxRule:
    source: str
    name: str
    rate: Decimal
    country_code: str | None
    category: str | None
    is_exempt: bool = False
    is_zero_rate: bool = False
    reason: str | None = None


@dataclass(slots=True)
class CalculatedItemTax:
    name: str
    category: str | None
    quantity: Decimal
    unit_price: Decimal
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    applied_rate: Decimal
    tax_label: str
    exempt_reason: str | None = None


@dataclass(slots=True)
class TaxComputationResult:
    subtotal_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    country_code: str | None
    items: list[CalculatedItemTax]
    breakdown: list[dict[str, Any]]
    prices_include_tax: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "subtotal_amount": float(self.subtotal_amount),
            "tax_amount": float(self.tax_amount),
            "total_amount": float(self.total_amount),
            "country_code": self.country_code,
            "prices_include_tax": self.prices_include_tax,
            "items": [
                {
                    "name": item.name,
                    "category": item.category,
                    "quantity": float(item.quantity),
                    "unit_price": float(item.unit_price),
                    "subtotal": float(item.subtotal),
                    "tax_amount": float(item.tax_amount),
                    "total": float(item.total),
                    "applied_rate": float(item.applied_rate),
                    "tax_label": item.tax_label,
                    "exempt_reason": item.exempt_reason,
                }
                for item in self.items
            ],
            "breakdown": self.breakdown,
        }


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


def _q2(value: Decimal) -> Decimal:
    return value.quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)


def _normalize_country(country_code: str | None) -> str | None:
    if not country_code:
        return None
    return country_code.strip().upper()[:2] or None


def _normalize_category(category: str | None) -> str | None:
    if not category:
        return None
    cleaned = category.strip().lower()
    return cleaned or None


def _today() -> date:
    return datetime.now(UTC).date()


async def _find_active_exemption(
    db: AsyncSession | None,
    *,
    store_id: int,
    customer_email: str | None,
    customer_phone: str | None,
    country_code: str | None,
    as_of: date,
) -> TaxExemption | None:
    if db is None or (not customer_email and not customer_phone):
        return None

    stmt = (
        select(TaxExemption)
        .where(
            TaxExemption.store_id == store_id,
            TaxExemption.is_active.is_(True),
            TaxExemption.valid_from <= as_of,
            or_(TaxExemption.valid_to.is_(None), TaxExemption.valid_to >= as_of),
        )
        .order_by(TaxExemption.country_code.is_(None), TaxExemption.id.desc())
    )
    result = await db.execute(stmt)
    for exemption in result.scalars().all():
        email_ok = bool(customer_email and exemption.customer_email and exemption.customer_email.lower() == customer_email.lower())
        phone_ok = bool(customer_phone and exemption.customer_phone and exemption.customer_phone == customer_phone)
        if not (email_ok or phone_ok):
            continue
        if exemption.country_code and exemption.country_code != country_code:
            continue
        return exemption
    return None


async def _resolve_tax_rule(
    db: AsyncSession | None,
    *,
    store: Store,
    country_code: str | None,
    category: str | None,
    customer_email: str | None,
    customer_phone: str | None,
    as_of: date,
    item_exempt: bool = False,
) -> AppliedTaxRule:
    normalized_country = _normalize_country(country_code or getattr(store, "default_tax_country", None) or getattr(store, "country", None))
    normalized_category = _normalize_category(category)

    if item_exempt:
        return AppliedTaxRule(
            source="product",
            name="TVA exonérée",
            rate=Decimal("0"),
            country_code=normalized_country,
            category=normalized_category,
            is_exempt=True,
            is_zero_rate=True,
            reason="product_marked_exempt",
        )

    exemption = await _find_active_exemption(
        db,
        store_id=getattr(store, "id", 0),
        customer_email=customer_email,
        customer_phone=customer_phone,
        country_code=normalized_country,
        as_of=as_of,
    )
    if exemption is not None:
        return AppliedTaxRule(
            source="exemption",
            name="TVA exonérée",
            rate=Decimal("0"),
            country_code=normalized_country,
            category=normalized_category,
            is_exempt=True,
            is_zero_rate=True,
            reason=exemption.reason,
        )

    if db is not None:
        stmt = (
            select(TaxRate)
            .where(
                TaxRate.is_active.is_(True),
                TaxRate.valid_from <= as_of,
                or_(TaxRate.valid_to.is_(None), TaxRate.valid_to >= as_of),
                or_(TaxRate.store_id.is_(None), TaxRate.store_id == store.id),
                or_(TaxRate.country_code.is_(None), TaxRate.country_code == normalized_country),
                or_(TaxRate.product_category.is_(None), TaxRate.product_category == normalized_category),
            )
            .order_by(
                TaxRate.store_id.is_(None),
                TaxRate.product_category.is_(None),
                TaxRate.country_code.is_(None),
                TaxRate.priority.asc(),
                TaxRate.valid_from.desc(),
                TaxRate.id.desc(),
            )
        )
        result = await db.execute(stmt)
        tax_rule = result.scalars().first()
        if tax_rule is not None:
            rate = _to_decimal(tax_rule.rate)
            return AppliedTaxRule(
                source="tax_rates",
                name=tax_rule.name or "TVA",
                rate=rate,
                country_code=tax_rule.country_code or normalized_country,
                category=tax_rule.product_category or normalized_category,
                is_exempt=bool(tax_rule.is_exempt),
                is_zero_rate=bool(tax_rule.is_zero_rate or rate == 0),
                reason=tax_rule.legal_reference,
            )

    fallback_rate = DEFAULT_COUNTRY_VAT.get(normalized_country or "", Decimal("0"))
    return AppliedTaxRule(
        source="fallback",
        name="TVA",
        rate=fallback_rate,
        country_code=normalized_country,
        category=normalized_category,
        is_zero_rate=fallback_rate == 0,
    )


async def calculate_taxes_for_items(
    *,
    db: AsyncSession | None,
    store: Store,
    items: list[dict[str, Any]],
    country_code: str | None = None,
    customer_email: str | None = None,
    customer_phone: str | None = None,
    prices_include_tax: bool | None = None,
    as_of: date | None = None,
) -> TaxComputationResult:
    calc_date = as_of or _today()
    include_tax = getattr(store, "tax_inclusive_pricing", True) if prices_include_tax is None else prices_include_tax
    normalized_country = _normalize_country(country_code or getattr(store, "default_tax_country", None) or getattr(store, "country", None))

    computed_items: list[CalculatedItemTax] = []
    for item in items or []:
        quantity = _to_decimal(item.get("qty", item.get("quantity", 1)), "1")
        unit_price = _to_decimal(item.get("unit_price", item.get("price", 0)), "0")
        category = _normalize_category(
            item.get("tax_category")
            or item.get("category")
            or item.get("product_category")
        )
        item_name = str(item.get("name") or item.get("product_name") or item.get("product") or "Produit")
        item_exempt = bool(item.get("is_tax_exempt") or item.get("tax_exempt"))

        rule = await _resolve_tax_rule(
            db,
            store=store,
            country_code=normalized_country,
            category=category,
            customer_email=customer_email,
            customer_phone=customer_phone,
            as_of=calc_date,
            item_exempt=item_exempt,
        )

        line_total_input = _q4(quantity * unit_price)
        if rule.is_exempt or rule.is_zero_rate or rule.rate == 0:
            subtotal = line_total_input
            tax_amount = Decimal("0")
            total = line_total_input
        elif include_tax:
            divisor = Decimal("1") + rule.rate
            subtotal = _q4(line_total_input / divisor)
            tax_amount = _q4(line_total_input - subtotal)
            total = line_total_input
        else:
            subtotal = line_total_input
            tax_amount = _q4(subtotal * rule.rate)
            total = _q4(subtotal + tax_amount)

        computed_items.append(
            CalculatedItemTax(
                name=item_name,
                category=category,
                quantity=quantity,
                unit_price=unit_price,
                subtotal=subtotal,
                tax_amount=tax_amount,
                total=total,
                applied_rate=rule.rate,
                tax_label=rule.name,
                exempt_reason=rule.reason if rule.is_exempt else None,
            )
        )

    subtotal_amount = _q4(sum((item.subtotal for item in computed_items), start=Decimal("0")))
    tax_amount = _q4(sum((item.tax_amount for item in computed_items), start=Decimal("0")))
    total_amount = _q4(sum((item.total for item in computed_items), start=Decimal("0")))

    breakdown_map: dict[tuple[str, str], dict[str, Any]] = {}
    for item in computed_items:
        key = (item.tax_label, str(item.applied_rate))
        entry = breakdown_map.setdefault(
            key,
            {
                "label": item.tax_label,
                "rate": float(item.applied_rate),
                "taxable_base": 0.0,
                "tax_amount": 0.0,
                "total": 0.0,
                "categories": set(),
            },
        )
        entry["taxable_base"] += float(item.subtotal)
        entry["tax_amount"] += float(item.tax_amount)
        entry["total"] += float(item.total)
        if item.category:
            entry["categories"].add(item.category)

    breakdown: list[dict[str, Any]] = []
    for entry in breakdown_map.values():
        categories = sorted(entry.pop("categories"))
        breakdown.append({
            **entry,
            "taxable_base": float(_q2(_to_decimal(entry["taxable_base"]))),
            "tax_amount": float(_q2(_to_decimal(entry["tax_amount"]))),
            "total": float(_q2(_to_decimal(entry["total"]))),
            "categories": categories,
        })

    return TaxComputationResult(
        subtotal_amount=subtotal_amount,
        tax_amount=tax_amount,
        total_amount=total_amount,
        country_code=normalized_country,
        items=computed_items,
        breakdown=breakdown,
        prices_include_tax=include_tax,
    )


async def calculate_order_taxes(
    db: AsyncSession | None,
    *,
    store: Store,
    order: Order,
    country_code: str | None = None,
    customer_email: str | None = None,
    customer_phone: str | None = None,
    prices_include_tax: bool | None = None,
) -> TaxComputationResult:
    return await calculate_taxes_for_items(
        db=db,
        store=store,
        items=list(order.items or []),
        country_code=country_code or getattr(order, "country_code", None) or getattr(store, "default_tax_country", None) or getattr(store, "country", None),
        customer_email=customer_email,
        customer_phone=customer_phone,
        prices_include_tax=prices_include_tax,
    )


async def calculate_manual_amount_taxes(
    db: AsyncSession | None,
    *,
    store: Store,
    description: str,
    amount: Decimal,
    country_code: str | None = None,
    category: str | None = None,
    customer_email: str | None = None,
    customer_phone: str | None = None,
    prices_include_tax: bool | None = None,
    is_tax_exempt: bool = False,
) -> TaxComputationResult:
    return await calculate_taxes_for_items(
        db=db,
        store=store,
        items=[
            {
                "name": description,
                "qty": 1,
                "unit_price": amount,
                "tax_category": category,
                "is_tax_exempt": is_tax_exempt,
            }
        ],
        country_code=country_code,
        customer_email=customer_email,
        customer_phone=customer_phone,
        prices_include_tax=prices_include_tax,
    )


async def migrate_legacy_tax_data(db: AsyncSession, *, store_id: int | None = None) -> dict[str, int]:
    order_stmt = select(Order)
    payment_stmt = select(PaymentLink)
    if store_id is not None:
        order_stmt = order_stmt.where(Order.store_id == store_id)
        payment_stmt = payment_stmt.where(PaymentLink.store_id == store_id)

    orders_result = await db.execute(order_stmt)
    links_result = await db.execute(payment_stmt)
    orders = orders_result.scalars().all()
    links = links_result.scalars().all()

    stores: dict[int, Store] = {}
    updated_orders = 0
    updated_links = 0

    async def _get_store(sid: int) -> Store | None:
        if sid in stores:
            return stores[sid]
        store = await db.get(Store, sid)
        if store is not None:
            stores[sid] = store
        return store

    for order in orders:
        if order.tax_breakdown and order.subtotal_amount is not None and order.tax_amount is not None:
            continue
        store = await _get_store(order.store_id)
        if store is None:
            continue
        result = await calculate_order_taxes(db, store=store, order=order)
        order.subtotal_amount = result.subtotal_amount
        order.tax_amount = result.tax_amount
        order.country_code = result.country_code
        order.tax_breakdown = result.breakdown
        if not getattr(order, "currency", None):
            order.currency = "TND" if (result.country_code or "") == "TN" else "EUR"
        updated_orders += 1

    for link in links:
        if link.tax_breakdown and link.subtotal_amount is not None and link.tax_amount is not None:
            continue
        store = await _get_store(link.store_id)
        if store is None:
            continue
        result = await calculate_manual_amount_taxes(
            db,
            store=store,
            description=link.description or "Paiement",
            amount=_to_decimal(link.amount),
            country_code=link.country_code or getattr(store, "default_tax_country", None) or getattr(store, "country", None),
            category=None,
            customer_email=link.customer_email,
            customer_phone=link.customer_phone,
            prices_include_tax=True,
        )
        link.subtotal_amount = result.subtotal_amount
        link.tax_amount = result.tax_amount
        link.country_code = result.country_code
        link.tax_breakdown = result.breakdown
        updated_links += 1

    await db.commit()
    return {"orders_updated": updated_orders, "payment_links_updated": updated_links}


async def enrich_order_items_with_product_tax_data(db: AsyncSession, *, store_id: int, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return []
    enriched: list[dict[str, Any]] = []
    for item in items:
        clone = dict(item)
        product_id = clone.get("product_id")
        if product_id and ("tax_category" not in clone or "is_tax_exempt" not in clone):
            product = await db.get(Product, product_id)
            if product is not None and product.store_id == store_id:
                clone.setdefault("tax_category", getattr(product, "tax_category", None) or getattr(product, "category", None))
                clone.setdefault("is_tax_exempt", bool(getattr(product, "is_tax_exempt", False)))
        enriched.append(clone)
    return enriched
