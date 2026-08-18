"""api/v1/tax.py — API TVA multi-pays (Bloc A1)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import get_store_id as _sid
from api.v1._deps import require_feature
from models.database import Store, TaxExemption, TaxRate, get_db
from services.tax_service import (
    calculate_manual_amount_taxes,
    migrate_legacy_tax_data,
)

# FIX: TVA incluse dès le plan "starter" (feature universelle).
# Sans cette gate, n'importe quel tenant free pouvait créer des TaxRate.
router = APIRouter(prefix="/tax", tags=["Tax"], dependencies=[require_feature("tax")])


class TaxRatePayload(BaseModel):
    country_code: str | None = Field(None, min_length=2, max_length=2)
    product_category: str | None = Field(None, max_length=100)
    rate: Decimal = Field(..., ge=0, le=1)
    is_zero_rate: bool = False
    is_exempt: bool = False
    valid_from: date
    valid_to: date | None = None
    priority: int = 100
    name: str = Field(default="TVA", max_length=100)
    legal_reference: str | None = Field(None, max_length=255)


class ExemptionPayload(BaseModel):
    customer_email: str | None = None
    customer_phone: str | None = None
    country_code: str | None = Field(None, min_length=2, max_length=2)
    reason: str = Field(..., max_length=255)
    valid_from: date
    valid_to: date | None = None


class TaxPreviewPayload(BaseModel):
    amount: Decimal = Field(..., gt=0)
    description: str = Field(..., min_length=1, max_length=255)
    country_code: str | None = Field(None, min_length=2, max_length=2)
    product_category: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    prices_include_tax: bool | None = None
    is_tax_exempt: bool = False


@router.get("/rates")
async def list_tax_rates(db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    stmt = (
        select(TaxRate)
        .where((TaxRate.store_id == store_id) | (TaxRate.store_id.is_(None)))
        .order_by(TaxRate.store_id.is_(None), TaxRate.country_code, TaxRate.product_category, TaxRate.valid_from.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": row.id,
                "store_id": row.store_id,
                "country_code": row.country_code,
                "product_category": row.product_category,
                "rate": float(row.rate),
                "is_zero_rate": row.is_zero_rate,
                "is_exempt": row.is_exempt,
                "valid_from": row.valid_from.isoformat(),
                "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                "priority": row.priority,
                "name": row.name,
                "legal_reference": row.legal_reference,
            }
            for row in rows
        ]
    }


@router.post("/rates", status_code=201)
async def create_tax_rate(body: TaxRatePayload, db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    row = TaxRate(
        store_id=store_id,
        country_code=body.country_code.upper() if body.country_code else None,
        product_category=body.product_category.lower() if body.product_category else None,
        rate=body.rate,
        is_zero_rate=body.is_zero_rate,
        is_exempt=body.is_exempt,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        priority=body.priority,
        name=body.name,
        legal_reference=body.legal_reference,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "status": "created"}


@router.get("/exemptions")
async def list_tax_exemptions(db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    stmt = select(TaxExemption).where(TaxExemption.store_id == store_id).order_by(TaxExemption.valid_from.desc(), TaxExemption.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": row.id,
                "customer_email": row.customer_email,
                "customer_phone": row.customer_phone,
                "country_code": row.country_code,
                "reason": row.reason,
                "valid_from": row.valid_from.isoformat(),
                "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                "is_active": row.is_active,
            }
            for row in rows
        ]
    }


@router.post("/exemptions", status_code=201)
async def create_tax_exemption(body: ExemptionPayload, db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    if not body.customer_email and not body.customer_phone:
        raise HTTPException(status_code=400, detail="customer_email ou customer_phone requis")
    row = TaxExemption(
        store_id=store_id,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        country_code=body.country_code.upper() if body.country_code else None,
        reason=body.reason,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "status": "created"}


@router.post("/preview")
async def preview_tax(body: TaxPreviewPayload, db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    store = await db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Store introuvable")
    result = await calculate_manual_amount_taxes(
        db,
        store=store,
        description=body.description,
        amount=body.amount,
        country_code=body.country_code,
        category=body.product_category,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        prices_include_tax=body.prices_include_tax,
        is_tax_exempt=body.is_tax_exempt,
    )
    return result.as_dict()


@router.post("/migrate-legacy")
async def migrate_legacy(db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    return await migrate_legacy_tax_data(db, store_id=store_id)
