from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import get_store_id, require_feature, require_role
from models.b2b_portal import B2BInvoice, B2BOrder, CompanyAccount, CompanyUser, PricingRule
from models.database import get_db
from services.b2b_portal_service import (
    add_company_user,
    approve_b2b_order,
    build_dashboard_snapshot,
    create_b2b_order,
    create_company_account,
    create_grouped_invoice,
    create_pricing_rule,
    quote_price,
)

router = APIRouter(prefix="/b2b", tags=["Plan F — B2B Portal"], dependencies=[require_feature("b2b_portal")])


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


class CompanyAccountIn(BaseModel):
    account_type: str = Field("garage", pattern="^(garage|reseller|wholesaler)$")
    name: str = Field(..., min_length=1, max_length=255)
    legal_name: str | None = None
    tax_id: str | None = None
    billing_email: str | None = None
    phone: str | None = None
    address: str | None = None
    credit_limit: float | None = None
    payment_terms_days: int = Field(30, ge=0, le=365)
    metadata_json: dict | None = None
    notes: str | None = None


class CompanyUserIn(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=255)
    role: str = Field("buyer", pattern="^(buyer|manager|approver|finance|admin)$")
    can_approve: bool = False
    user_id: int | None = None


class PricingRuleIn(BaseModel):
    rule_type: str = Field(..., pattern="^(negotiated|tiered|discount|contract)$")
    product_id: int | None = None
    variant_id: int | None = None
    contract_code: str | None = None
    currency: str = Field("EUR", min_length=3, max_length=3)
    min_qty: int = Field(1, ge=1, le=100000)
    negotiated_unit_price: float | None = None
    discount_percent: float | None = None
    rebate_percent: float | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    terms: dict | None = None


class QuoteIn(BaseModel):
    company_account_id: int
    product_id: int | None = None
    variant_id: int | None = None
    qty: int = Field(1, ge=1, le=100000)
    base_unit_price: float = Field(..., ge=0)


class B2BOrderItemIn(BaseModel):
    product_id: int | None = None
    variant_id: int | None = None
    sku: str | None = None
    name: str | None = None
    qty: int = Field(1, ge=1, le=100000)
    base_unit_price: float | None = Field(None, ge=0)


class B2BOrderIn(BaseModel):
    company_account_id: int
    po_number: str | None = None
    internal_reference: str | None = None
    currency: str = Field("EUR", min_length=3, max_length=3)
    payment_terms_days: int | None = Field(None, ge=0, le=365)
    validation_chain: list | None = None
    notes: str | None = None
    auto_approve: bool = False
    items: list[B2BOrderItemIn] = Field(default_factory=list, min_length=1, max_length=500)


class GroupInvoiceIn(BaseModel):
    company_account_id: int
    order_ids: list[int] = Field(..., min_length=1, max_length=500)
    grouped_period_label: str | None = None
    payment_mode: str = Field("deferred", max_length=32)
    notes: str | None = None


class CompanyAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    store_id: int
    account_type: str
    name: str
    legal_name: str | None
    tax_id: str | None
    billing_email: str | None
    phone: str | None
    address: str | None
    status: str
    credit_limit: Decimal | None
    payment_terms_days: int
    metadata_json: dict | None
    notes: str | None
    created_at: datetime | None
    updated_at: datetime | None


class CompanyUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_account_id: int
    full_name: str
    email: str
    role: str
    can_approve: bool
    is_active: bool
    created_at: datetime | None


class PricingRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_account_id: int
    product_id: int | None
    variant_id: int | None
    rule_type: str
    contract_code: str | None
    currency: str
    min_qty: int
    negotiated_unit_price: Decimal | None
    discount_percent: Decimal | None
    rebate_percent: Decimal | None
    starts_at: datetime | None
    ends_at: datetime | None
    terms: dict | None
    is_active: bool


class B2BOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_account_id: int
    approval_status: str
    po_number: str | None
    internal_reference: str | None
    currency: str
    payment_terms_days: int
    due_date: date | None
    subtotal_amount: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    items: list
    validation_chain: list | None
    history: list | None
    notes: str | None
    invoice_number: str | None
    approved_by_user_id: int | None
    approved_at: datetime | None
    created_at: datetime | None


class B2BInvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_account_id: int
    invoice_number: str
    grouped_order_ids: list
    status: str
    issue_date: date
    due_date: date | None
    grouped_period_label: str | None
    payment_mode: str
    currency: str
    subtotal_amount: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    amount_paid: Decimal
    notes: str | None
    created_at: datetime | None


@router.get("/accounts", response_model=list[CompanyAccountOut], dependencies=[require_role("viewer")])
async def list_company_accounts(session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    res = await session.execute(select(CompanyAccount).where(CompanyAccount.store_id == store_id).order_by(CompanyAccount.created_at.desc()))
    return [CompanyAccountOut.model_validate(row) for row in res.scalars().all()]


@router.post("/accounts", response_model=CompanyAccountOut, dependencies=[require_role("manager")])
async def create_account(payload: CompanyAccountIn, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    row = await create_company_account(
        session,
        store_id=store_id,
        account_type=payload.account_type,
        name=payload.name,
        legal_name=payload.legal_name,
        tax_id=payload.tax_id,
        billing_email=payload.billing_email,
        phone=payload.phone,
        address=payload.address,
        credit_limit=Decimal(str(payload.credit_limit)) if payload.credit_limit is not None else None,
        payment_terms_days=payload.payment_terms_days,
        metadata_json=payload.metadata_json,
        notes=payload.notes,
    )
    await session.commit()
    await session.refresh(row)
    return CompanyAccountOut.model_validate(row)


@router.post("/accounts/{company_account_id}/users", response_model=CompanyUserOut, dependencies=[require_role("manager")])
async def create_company_contact(company_account_id: int, payload: CompanyUserIn, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    try:
        row = await add_company_user(
            session,
            store_id=store_id,
            company_account_id=company_account_id,
            full_name=payload.full_name,
            email=payload.email,
            role=payload.role,
            can_approve=payload.can_approve,
            user_id=payload.user_id,
        )
    except ValueError as exc:
        raise _bad_request(exc)
    await session.commit()
    await session.refresh(row)
    return CompanyUserOut.model_validate(row)


@router.get("/accounts/{company_account_id}/users", response_model=list[CompanyUserOut], dependencies=[require_role("viewer")])
async def list_company_contacts(company_account_id: int, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    res = await session.execute(
        select(CompanyUser).where(CompanyUser.store_id == store_id, CompanyUser.company_account_id == company_account_id).order_by(CompanyUser.created_at.desc())
    )
    return [CompanyUserOut.model_validate(row) for row in res.scalars().all()]


@router.post("/accounts/{company_account_id}/pricing", response_model=PricingRuleOut, dependencies=[require_role("manager")])
async def create_company_pricing(company_account_id: int, payload: PricingRuleIn, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    try:
        row = await create_pricing_rule(
            session,
            store_id=store_id,
            company_account_id=company_account_id,
            rule_type=payload.rule_type,
            product_id=payload.product_id,
            variant_id=payload.variant_id,
            contract_code=payload.contract_code,
            currency=payload.currency.upper(),
            min_qty=payload.min_qty,
            negotiated_unit_price=Decimal(str(payload.negotiated_unit_price)) if payload.negotiated_unit_price is not None else None,
            discount_percent=Decimal(str(payload.discount_percent)) if payload.discount_percent is not None else None,
            rebate_percent=Decimal(str(payload.rebate_percent)) if payload.rebate_percent is not None else None,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            terms=payload.terms,
        )
    except ValueError as exc:
        raise _bad_request(exc)
    await session.commit()
    await session.refresh(row)
    return PricingRuleOut.model_validate(row)


@router.get("/accounts/{company_account_id}/pricing", response_model=list[PricingRuleOut], dependencies=[require_role("viewer")])
async def list_company_pricing(company_account_id: int, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    res = await session.execute(
        select(PricingRule)
        .where(PricingRule.store_id == store_id, PricingRule.company_account_id == company_account_id)
        .order_by(PricingRule.created_at.desc())
    )
    return [PricingRuleOut.model_validate(row) for row in res.scalars().all()]


@router.post("/pricing/quote")
async def quote(payload: QuoteIn, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    try:
        row = await quote_price(
            session,
            store_id=store_id,
            company_account_id=payload.company_account_id,
            product_id=payload.product_id,
            variant_id=payload.variant_id,
            qty=payload.qty,
            base_unit_price=Decimal(str(payload.base_unit_price)),
        )
    except ValueError as exc:
        raise _bad_request(exc)
    return {
        "base_unit_price": float(row.base_unit_price),
        "final_unit_price": float(row.final_unit_price),
        "discount_amount": float(row.discount_amount),
        "applied_rule_id": row.applied_rule_id,
        "applied_rule_type": row.applied_rule_type,
        "contract_code": row.contract_code,
        "explanation": row.explanation,
    }


@router.get("/orders", response_model=list[B2BOrderOut], dependencies=[require_role("viewer")])
async def list_orders(session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    res = await session.execute(select(B2BOrder).where(B2BOrder.store_id == store_id).order_by(B2BOrder.created_at.desc()))
    return [B2BOrderOut.model_validate(row) for row in res.scalars().all()]


@router.post("/orders", response_model=B2BOrderOut, dependencies=[require_role("manager")])
async def create_order(payload: B2BOrderIn, request: Request, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    user_id = getattr(request.state, "user_id", None)
    try:
        row = await create_b2b_order(
            session,
            store_id=store_id,
            company_account_id=payload.company_account_id,
            created_by_user_id=user_id,
            po_number=payload.po_number,
            internal_reference=payload.internal_reference,
            currency=payload.currency.upper(),
            payment_terms_days=payload.payment_terms_days,
            validation_chain=payload.validation_chain,
            notes=payload.notes,
            auto_approve=payload.auto_approve,
            items=[item.model_dump() for item in payload.items],
        )
    except ValueError as exc:
        raise _bad_request(exc)
    await session.commit()
    await session.refresh(row)
    return B2BOrderOut.model_validate(row)


@router.post("/orders/{order_id}/approve", response_model=B2BOrderOut, dependencies=[require_role("admin")])
async def approve_order(order_id: int, request: Request, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    try:
        row = await approve_b2b_order(
            session,
            store_id=store_id,
            order_id=order_id,
            reviewer_user_id=getattr(request.state, "user_id", None),
        )
    except ValueError as exc:
        raise _bad_request(exc)
    await session.commit()
    await session.refresh(row)
    return B2BOrderOut.model_validate(row)


@router.get("/invoices", response_model=list[B2BInvoiceOut], dependencies=[require_role("viewer")])
async def list_invoices(session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    res = await session.execute(select(B2BInvoice).where(B2BInvoice.store_id == store_id).order_by(B2BInvoice.created_at.desc()))
    return [B2BInvoiceOut.model_validate(row) for row in res.scalars().all()]


@router.post("/invoices/grouped", response_model=B2BInvoiceOut, dependencies=[require_role("admin")])
async def grouped_invoice(payload: GroupInvoiceIn, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    try:
        row = await create_grouped_invoice(
            session,
            store_id=store_id,
            company_account_id=payload.company_account_id,
            order_ids=payload.order_ids,
            grouped_period_label=payload.grouped_period_label,
            payment_mode=payload.payment_mode,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise _bad_request(exc)
    await session.commit()
    await session.refresh(row)
    return B2BInvoiceOut.model_validate(row)


@router.get("/dashboard", dependencies=[require_role("viewer")])
async def dashboard(session: AsyncSession = Depends(get_db)):
    return await build_dashboard_snapshot(session, store_id=get_store_id())
