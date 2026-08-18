from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.b2b_portal import (
    B2BInvoice,
    B2BOrderApprovalStatus,
    CompanyAccount,
    CompanyAccountType,
    CompanyUser,
    PricingRule,
)
from models.database import Base, Product, Store
from services.b2b_portal_service import (
    add_company_user,
    approve_b2b_order,
    create_b2b_order,
    create_company_account,
    create_grouped_invoice,
    create_pricing_rule,
    quote_price,
)


@pytest.mark.asyncio
async def test_quote_price_prefers_negotiated_rule() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        store = Store(name="AC", slug="ac-b2b", default_tax_country="FR", country="FR", tax_inclusive_pricing=False)
        session.add(store)
        await session.flush()

        product = Product(store_id=store.id, name="Pneu Pro", price=Decimal("100.00"), stock_qty=20, category="tires")
        session.add(product)
        await session.flush()

        company = await create_company_account(
            session,
            store_id=store.id,
            account_type=CompanyAccountType.GARAGE.value,
            name="Garage Atlas",
            payment_terms_days=45,
        )
        await create_pricing_rule(
            session,
            store_id=store.id,
            company_account_id=company.id,
            rule_type="discount",
            product_id=product.id,
            discount_percent=Decimal("10.0"),
        )
        await create_pricing_rule(
            session,
            store_id=store.id,
            company_account_id=company.id,
            rule_type="negotiated",
            product_id=product.id,
            negotiated_unit_price=Decimal("79.5000"),
        )
        await session.commit()

        quote = await quote_price(
            session,
            store_id=store.id,
            company_account_id=company.id,
            product_id=product.id,
            qty=3,
            base_unit_price=Decimal("100.00"),
        )

        assert quote.applied_rule_type == "negotiated"
        assert quote.final_unit_price == Decimal("79.5000")
        assert quote.discount_amount == Decimal("20.5000")

    await engine.dispose()


@pytest.mark.asyncio
async def test_b2b_order_approval_and_grouped_invoice() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        store = Store(name="AC2", slug="ac-b2b-2", default_tax_country="FR", country="FR", tax_inclusive_pricing=False)
        session.add(store)
        await session.flush()

        product = Product(store_id=store.id, name="Filtre", price=Decimal("50.00"), stock_qty=50, category="parts")
        session.add(product)
        await session.flush()

        company = await create_company_account(session, store_id=store.id, account_type="reseller", name="Pièces Nord", payment_terms_days=30)
        approver = await add_company_user(
            session,
            store_id=store.id,
            company_account_id=company.id,
            full_name="Fatma Ops",
            email="fatma@example.com",
            role="approver",
            can_approve=True,
        )
        await create_pricing_rule(
            session,
            store_id=store.id,
            company_account_id=company.id,
            rule_type="tiered",
            product_id=product.id,
            min_qty=5,
            discount_percent=Decimal("15.0"),
        )
        await session.commit()

        order = await create_b2b_order(
            session,
            store_id=store.id,
            company_account_id=company.id,
            created_by_user_id=None,
            po_number="PO-2026-001",
            internal_reference="INT-001",
            currency="EUR",
            payment_terms_days=30,
            validation_chain=[{"step": 1, "role": "approver"}],
            notes="Urgent garage",
            auto_approve=False,
            items=[{"product_id": product.id, "name": "Filtre", "qty": 5}],
        )
        await session.flush()
        assert order.approval_status == B2BOrderApprovalStatus.PENDING_APPROVAL
        assert order.discount_amount > 0

        approved = await approve_b2b_order(
            session,
            store_id=store.id,
            order_id=order.id,
            reviewer_user_id=approver.user_id,
            note="Validé finance",
        )
        await session.flush()
        assert approved.approval_status == B2BOrderApprovalStatus.APPROVED

        invoice = await create_grouped_invoice(
            session,
            store_id=store.id,
            company_account_id=company.id,
            order_ids=[order.id],
            grouped_period_label="Juin 2026",
            payment_mode="credit",
        )
        await session.commit()
        await session.refresh(invoice)
        await session.refresh(order)

        assert invoice.invoice_number.startswith("B2B-")
        assert invoice.grouped_order_ids == [order.id]
        assert order.invoice_number == invoice.invoice_number
        assert invoice.total_amount >= order.total_amount

    await engine.dispose()
