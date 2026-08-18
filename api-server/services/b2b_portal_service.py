from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.b2b_portal import (
    B2BInvoice,
    B2BInvoiceStatus,
    B2BOrder,
    B2BOrderApprovalStatus,
    CompanyAccount,
    CompanyAccountStatus,
    CompanyUser,
    PricingRule,
    PricingRuleType,
)
from models.database import Product, ProductVariant, Store
from services.b2b_metrics import (
    b2b_accounts_created_total,
    b2b_grouped_invoices_created_total,
    b2b_orders_approved_total,
    b2b_orders_created_total,
    b2b_quote_requests_total,
)
from services.tax_service import calculate_manual_amount_taxes

logger = logging.getLogger(__name__)
TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


def _d(value: object | None, quant: Decimal = FOUR) -> Decimal:
    if value is None or value == "":
        return Decimal("0").quantize(quant)
    if isinstance(value, Decimal):
        return value.quantize(quant, rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return _now().date()


def _invoice_number(store_id: int, company_account_id: int) -> str:
    stamp = _now().strftime("%Y%m%d%H%M%S")
    return f"B2B-{store_id:04d}-{company_account_id:04d}-{stamp}"


@dataclass(slots=True)
class QuoteResult:
    base_unit_price: Decimal
    final_unit_price: Decimal
    discount_amount: Decimal
    applied_rule_id: int | None
    applied_rule_type: str | None
    contract_code: str | None
    explanation: str


async def get_company_or_404(session: AsyncSession, *, store_id: int, company_account_id: int) -> CompanyAccount:
    company = await session.get(CompanyAccount, company_account_id)
    if company is None or company.store_id != store_id:
        raise ValueError("Compte entreprise introuvable")
    return company


async def create_company_account(
    session: AsyncSession,
    *,
    store_id: int,
    account_type: str,
    name: str,
    legal_name: str | None = None,
    tax_id: str | None = None,
    billing_email: str | None = None,
    phone: str | None = None,
    address: str | None = None,
    credit_limit: Decimal | None = None,
    payment_terms_days: int = 30,
    metadata_json: dict | None = None,
    notes: str | None = None,
) -> CompanyAccount:
    company = CompanyAccount(
        store_id=store_id,
        account_type=account_type,
        name=name,
        legal_name=legal_name,
        tax_id=tax_id,
        billing_email=billing_email,
        phone=phone,
        address=address,
        status=CompanyAccountStatus.ACTIVE,
        credit_limit=credit_limit,
        payment_terms_days=payment_terms_days,
        metadata_json=metadata_json,
        notes=notes,
    )
    session.add(company)
    await session.flush()
    b2b_accounts_created_total.labels(str(store_id), str(account_type)).inc()
    logger.info("b2b.company_account_created", extra={"store_id": store_id, "company_account_id": company.id, "account_type": account_type})
    return company


async def add_company_user(
    session: AsyncSession,
    *,
    store_id: int,
    company_account_id: int,
    full_name: str,
    email: str,
    role: str,
    can_approve: bool = False,
    user_id: int | None = None,
) -> CompanyUser:
    await get_company_or_404(session, store_id=store_id, company_account_id=company_account_id)
    row = CompanyUser(
        store_id=store_id,
        company_account_id=company_account_id,
        full_name=full_name,
        email=email,
        role=role,
        can_approve=can_approve,
        user_id=user_id,
    )
    session.add(row)
    await session.flush()
    return row


async def create_pricing_rule(
    session: AsyncSession,
    *,
    store_id: int,
    company_account_id: int,
    rule_type: str,
    product_id: int | None = None,
    variant_id: int | None = None,
    contract_code: str | None = None,
    currency: str = "EUR",
    min_qty: int = 1,
    negotiated_unit_price: Decimal | None = None,
    discount_percent: Decimal | None = None,
    rebate_percent: Decimal | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    terms: dict | None = None,
) -> PricingRule:
    await get_company_or_404(session, store_id=store_id, company_account_id=company_account_id)
    row = PricingRule(
        store_id=store_id,
        company_account_id=company_account_id,
        product_id=product_id,
        variant_id=variant_id,
        rule_type=rule_type,
        contract_code=contract_code,
        currency=currency,
        min_qty=max(1, int(min_qty or 1)),
        negotiated_unit_price=negotiated_unit_price,
        discount_percent=discount_percent,
        rebate_percent=rebate_percent,
        starts_at=starts_at,
        ends_at=ends_at,
        terms=terms,
    )
    session.add(row)
    await session.flush()
    return row


async def quote_price(
    session: AsyncSession,
    *,
    store_id: int,
    company_account_id: int,
    base_unit_price: Decimal,
    qty: int,
    product_id: int | None = None,
    variant_id: int | None = None,
) -> QuoteResult:
    await get_company_or_404(session, store_id=store_id, company_account_id=company_account_id)
    b2b_quote_requests_total.labels(str(store_id)).inc()
    now = _now()
    stmt = (
        select(PricingRule)
        .where(
            PricingRule.store_id == store_id,
            PricingRule.company_account_id == company_account_id,
            PricingRule.is_active,
        )
        .order_by(PricingRule.variant_id.desc(), PricingRule.product_id.desc(), PricingRule.min_qty.desc())
    )
    res = await session.execute(stmt)
    rules = res.scalars().all()

    price = _d(base_unit_price)
    best = QuoteResult(
        base_unit_price=price,
        final_unit_price=price,
        discount_amount=Decimal("0.0000"),
        applied_rule_id=None,
        applied_rule_type=None,
        contract_code=None,
        explanation="Tarif catalogue",
    )

    priority = {
        PricingRuleType.NEGOTIATED.value: 1,
        PricingRuleType.CONTRACT.value: 2,
        PricingRuleType.TIERED.value: 3,
        PricingRuleType.DISCOUNT.value: 4,
    }

    candidates: list[tuple[int, Decimal, QuoteResult]] = []
    for rule in rules:
        if rule.variant_id is not None and variant_id != rule.variant_id:
            continue
        if rule.product_id is not None and product_id != rule.product_id:
            continue
        if qty < int(rule.min_qty or 1):
            continue
        if rule.starts_at and rule.starts_at > now:
            continue
        if rule.ends_at and rule.ends_at < now:
            continue

        if rule.rule_type in (PricingRuleType.NEGOTIATED, PricingRuleType.CONTRACT) and rule.negotiated_unit_price is not None:
            final = _d(rule.negotiated_unit_price)
            explanation = f"Tarif négocié ({rule.contract_code or 'contrat'})"
        else:
            pct = _d(rule.discount_percent or 0)
            rebate = _d(rule.rebate_percent or 0)
            total_pct = pct + rebate
            final = (price * (Decimal("1") - (total_pct / Decimal("100")))).quantize(FOUR, rounding=ROUND_HALF_UP)
            explanation = f"Remise {total_pct}%"

        if final < 0:
            final = Decimal("0.0000")

        quote = QuoteResult(
            base_unit_price=price,
            final_unit_price=final,
            discount_amount=(price - final).quantize(FOUR, rounding=ROUND_HALF_UP),
            applied_rule_id=rule.id,
            applied_rule_type=rule.rule_type.value if hasattr(rule.rule_type, "value") else str(rule.rule_type),
            contract_code=rule.contract_code,
            explanation=explanation,
        )
        candidates.append((priority.get(quote.applied_rule_type or "", 99), final, quote))

    if candidates:
        best = sorted(candidates, key=lambda item: (item[1], item[0]))[0][2]

    logger.info(
        "b2b.quote_price",
        extra={
            "store_id": store_id,
            "company_account_id": company_account_id,
            "product_id": product_id,
            "variant_id": variant_id,
            "qty": qty,
            "final_unit_price": str(best.final_unit_price),
            "applied_rule_id": best.applied_rule_id,
        },
    )
    return best


async def _resolve_item_base_price(
    session: AsyncSession,
    *,
    store_id: int,
    product_id: int | None,
    variant_id: int | None,
    provided_unit_price: Decimal | None,
) -> Decimal:
    if provided_unit_price is not None:
        return _d(provided_unit_price)
    if variant_id is not None:
        variant = await session.get(ProductVariant, variant_id)
        if variant and variant.store_id == store_id:
            if getattr(variant, "price_override", None) is not None:
                return _d(variant.price_override)
            product = await session.get(Product, variant.product_id)
            if product and product.store_id == store_id:
                return _d(product.price)
    if product_id is not None:
        product = await session.get(Product, product_id)
        if product and product.store_id == store_id:
            return _d(product.price)
    return Decimal("0.0000")


async def create_b2b_order(
    session: AsyncSession,
    *,
    store_id: int,
    company_account_id: int,
    created_by_user_id: int | None,
    po_number: str | None,
    internal_reference: str | None,
    currency: str,
    items: list[dict],
    validation_chain: list | None = None,
    notes: str | None = None,
    payment_terms_days: int | None = None,
    auto_approve: bool = False,
) -> B2BOrder:
    company = await get_company_or_404(session, store_id=store_id, company_account_id=company_account_id)
    if company.status == CompanyAccountStatus.SUSPENDED:
        raise ValueError("Compte entreprise suspendu")

    priced_items: list[dict] = []
    subtotal = Decimal("0.0000")
    discount_total = Decimal("0.0000")
    for raw in items:
        qty = max(1, int(raw.get("qty", 1)))
        product_id = raw.get("product_id")
        variant_id = raw.get("variant_id")
        base = await _resolve_item_base_price(
            session,
            store_id=store_id,
            product_id=product_id,
            variant_id=variant_id,
            provided_unit_price=_d(raw.get("base_unit_price")) if raw.get("base_unit_price") is not None else None,
        )
        quote = await quote_price(
            session,
            store_id=store_id,
            company_account_id=company_account_id,
            base_unit_price=base,
            qty=qty,
            product_id=product_id,
            variant_id=variant_id,
        )
        line_total = (quote.final_unit_price * Decimal(qty)).quantize(FOUR, rounding=ROUND_HALF_UP)
        subtotal += line_total
        discount_total += (quote.discount_amount * Decimal(qty)).quantize(FOUR, rounding=ROUND_HALF_UP)
        priced_items.append(
            {
                "product_id": product_id,
                "variant_id": variant_id,
                "sku": raw.get("sku"),
                "name": raw.get("name") or raw.get("sku") or f"Product #{product_id or variant_id or 'n/a'}",
                "qty": qty,
                "base_unit_price": float(quote.base_unit_price),
                "unit_price": float(quote.final_unit_price),
                "line_total": float(line_total),
                "pricing_rule_id": quote.applied_rule_id,
                "pricing_rule_type": quote.applied_rule_type,
                "contract_code": quote.contract_code,
                "price_explanation": quote.explanation,
            }
        )

    terms_days = int(payment_terms_days or company.payment_terms_days or 30)
    store = await session.get(Store, store_id)
    tax_result = await calculate_manual_amount_taxes(
        session,
        store=store,
        description=f"Commande B2B {company.name}",
        amount=subtotal,
        country_code=getattr(store, "default_tax_country", None) or getattr(store, "country", None),
        prices_include_tax=False,
    )
    total = _d(tax_result.total_amount)
    tax_amount = _d(tax_result.tax_amount)
    approval_status = B2BOrderApprovalStatus.APPROVED if auto_approve else B2BOrderApprovalStatus.PENDING_APPROVAL
    history = [
        {
            "at": _now().isoformat(),
            "event": "created",
            "by_user_id": created_by_user_id,
            "status": approval_status.value,
        }
    ]
    order = B2BOrder(
        store_id=store_id,
        company_account_id=company_account_id,
        created_by_user_id=created_by_user_id,
        approval_status=approval_status,
        po_number=po_number,
        internal_reference=internal_reference,
        currency=currency,
        payment_terms_days=terms_days,
        due_date=_today() + timedelta(days=terms_days),
        subtotal_amount=subtotal,
        tax_amount=tax_amount,
        discount_amount=discount_total,
        total_amount=total,
        items=priced_items,
        validation_chain=validation_chain or [],
        history=history,
        notes=notes,
        approved_by_user_id=created_by_user_id if auto_approve else None,
        approved_at=_now() if auto_approve else None,
    )
    session.add(order)
    await session.flush()
    b2b_orders_created_total.labels(str(store_id), approval_status.value).inc()
    logger.info("b2b.order_created", extra={"store_id": store_id, "b2b_order_id": order.id, "approval_status": approval_status.value, "company_account_id": company_account_id})
    return order


async def approve_b2b_order(
    session: AsyncSession,
    *,
    store_id: int,
    order_id: int,
    reviewer_user_id: int | None,
    note: str | None = None,
) -> B2BOrder:
    order = await session.get(B2BOrder, order_id)
    if order is None or order.store_id != store_id:
        raise ValueError("Commande B2B introuvable")
    if order.approval_status not in {B2BOrderApprovalStatus.PENDING_APPROVAL, B2BOrderApprovalStatus.DRAFT}:
        raise ValueError("Cette commande ne peut plus être approuvée")

    order.approval_status = B2BOrderApprovalStatus.APPROVED
    order.approved_by_user_id = reviewer_user_id
    order.approved_at = _now()
    history = list(order.history or [])
    history.append({
        "at": _now().isoformat(),
        "event": "approved",
        "by_user_id": reviewer_user_id,
        "note": note,
        "status": order.approval_status.value,
    })
    order.history = history
    b2b_orders_approved_total.labels(str(store_id)).inc()
    logger.info("b2b.order_approved", extra={"store_id": store_id, "b2b_order_id": order.id, "reviewer_user_id": reviewer_user_id})
    return order


async def create_grouped_invoice(
    session: AsyncSession,
    *,
    store_id: int,
    company_account_id: int,
    order_ids: list[int],
    grouped_period_label: str | None = None,
    payment_mode: str = "deferred",
    notes: str | None = None,
) -> B2BInvoice:
    if not order_ids:
        raise ValueError("Aucune commande fournie pour la facture groupée")

    company = await get_company_or_404(session, store_id=store_id, company_account_id=company_account_id)
    stmt = select(B2BOrder).where(
        B2BOrder.store_id == store_id,
        B2BOrder.company_account_id == company_account_id,
        B2BOrder.id.in_(order_ids),
    )
    res = await session.execute(stmt)
    orders = res.scalars().all()
    if len(orders) != len(set(order_ids)):
        raise ValueError("Certaines commandes B2B sont introuvables")

    for order in orders:
        if order.approval_status != B2BOrderApprovalStatus.APPROVED:
            raise ValueError("Toutes les commandes doivent être approuvées avant la facturation groupée")
        if order.invoice_number:
            raise ValueError("Une ou plusieurs commandes sont déjà facturées")

    subtotal = sum((_d(o.subtotal_amount) for o in orders), Decimal("0.0000"))
    tax_amount = sum((_d(o.tax_amount) for o in orders), Decimal("0.0000"))
    discount_amount = sum((_d(o.discount_amount) for o in orders), Decimal("0.0000"))
    total = sum((_d(o.total_amount) for o in orders), Decimal("0.0000"))

    # BUG#7 audit verification: tax_amount is correctly summed from each
    # B2BOrder.tax_amount, which is itself computed via calculate_manual_amount_taxes
    # at order creation time (see create_b2b_order above). This is NOT zero by
    # default — defensive check below catches any future regression where an
    # order bypasses tax calculation (e.g. legacy import, manual DB insert).
    if subtotal > 0 and tax_amount == 0:
        logger.warning(
            "create_grouped_invoice: tax_amount=0 with subtotal=%s for orders=%s "
            "— verify these orders went through calculate_manual_amount_taxes",
            subtotal, [o.id for o in orders],
        )

    invoice = B2BInvoice(
        store_id=store_id,
        company_account_id=company_account_id,
        invoice_number=_invoice_number(store_id, company_account_id),
        grouped_order_ids=[o.id for o in orders],
        status=B2BInvoiceStatus.ISSUED,
        issue_date=_today(),
        due_date=_today() + timedelta(days=int(company.payment_terms_days or 30)),
        grouped_period_label=grouped_period_label,
        payment_mode=payment_mode,
        currency=orders[0].currency if orders else "EUR",
        subtotal_amount=subtotal,
        tax_amount=tax_amount,
        discount_amount=discount_amount,
        total_amount=total,
        amount_paid=Decimal("0.00"),
        notes=notes,
    )
    session.add(invoice)
    await session.flush()

    now = _now()
    for order in orders:
        order.invoice_number = invoice.invoice_number
        order.invoiced_at = now
        hist = list(order.history or [])
        hist.append({
            "at": now.isoformat(),
            "event": "group_invoiced",
            "invoice_number": invoice.invoice_number,
        })
        order.history = hist

    b2b_grouped_invoices_created_total.labels(str(store_id)).inc()
    logger.info("b2b.grouped_invoice_created", extra={"store_id": store_id, "invoice_number": invoice.invoice_number, "order_count": len(orders), "company_account_id": company_account_id})
    return invoice


async def build_dashboard_snapshot(session: AsyncSession, *, store_id: int) -> dict:
    accounts_total = (await session.execute(select(func.count()).select_from(CompanyAccount).where(CompanyAccount.store_id == store_id))).scalar_one()
    pending_orders = (await session.execute(select(func.count()).select_from(B2BOrder).where(B2BOrder.store_id == store_id, B2BOrder.approval_status == B2BOrderApprovalStatus.PENDING_APPROVAL))).scalar_one()
    overdue_invoices = (await session.execute(select(func.count()).select_from(B2BInvoice).where(B2BInvoice.store_id == store_id, B2BInvoice.due_date < _today(), B2BInvoice.status.in_([B2BInvoiceStatus.ISSUED, B2BInvoiceStatus.PARTIALLY_PAID])))).scalar_one()
    credit_exposure = (await session.execute(select(func.coalesce(func.sum(B2BInvoice.total_amount - B2BInvoice.amount_paid), 0)).where(B2BInvoice.store_id == store_id, B2BInvoice.status.in_([B2BInvoiceStatus.ISSUED, B2BInvoiceStatus.PARTIALLY_PAID, B2BInvoiceStatus.OVERDUE])))).scalar_one()
    return {
        "accounts_total": int(accounts_total or 0),
        "pending_orders": int(pending_orders or 0),
        "overdue_invoices": int(overdue_invoices or 0),
        "credit_exposure": float(_d(credit_exposure, TWO)),
    }
