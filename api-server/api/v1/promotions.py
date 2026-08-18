"""api/v1/promotions.py — Plan B promotions & marketing."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import get_store_id as _sid
from api.v1._deps import require_feature
from models.database import Campaign, Coupon, Promotion, PromotionRule, Store, get_db
from services.promotions_service import (
    apply_promotions_to_items,
    generate_smart_recommendations,
)
from services.tax_service import calculate_taxes_for_items

router = APIRouter(prefix="/promotions", tags=["Promotions"], dependencies=[require_feature("promotions")])


class CampaignPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    channel: str | None = Field(None, max_length=50)
    trigger_type: str | None = Field(None, max_length=50)
    status: str = Field(default="draft", max_length=20)
    start_at: datetime | None = None
    end_at: datetime | None = None
    config: dict | None = None


class RulePayload(BaseModel):
    name: str | None = Field(None, max_length=255)
    rule_type: str = Field(default="conditions", max_length=50)
    conditions: dict | None = None
    is_active: bool = True
    priority: int = 100


class PromotionPayload(BaseModel):
    campaign_id: int | None = None
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    promotion_type: str = Field(default="automatic", max_length=30)
    discount_type: str = Field(default="percentage", max_length=30)
    discount_value: Decimal | None = Field(None, ge=0)
    applies_to: str = Field(default="all", max_length=30)
    eligible_product_ids: list[int] | None = None
    eligible_categories: list[str] | None = None
    eligible_brands: list[str] | None = None
    gift_product_id: int | None = None
    gift_name: str | None = Field(None, max_length=255)
    gift_quantity: int = Field(default=1, ge=1)
    priority: int = 100
    stackable: bool = False
    start_at: datetime | None = None
    end_at: datetime | None = None
    customer_segment: str | None = Field(None, max_length=30)
    country_codes: list[str] | None = None
    channel_codes: list[str] | None = None
    max_global_uses: int | None = Field(None, ge=1)
    max_uses_per_customer: int | None = Field(None, ge=1)
    max_discount_amount: Decimal | None = Field(None, ge=0)
    is_active: bool = True
    config: dict | None = None
    rules: list[RulePayload] = Field(default_factory=list)

    @field_validator("promotion_type")
    @classmethod
    def validate_promotion_type(cls, value: str) -> str:
        allowed = {"automatic", "coupon", "smart"}
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise ValueError(f"promotion_type invalide: {value}")
        return normalized

    @field_validator("discount_type")
    @classmethod
    def validate_discount_type(cls, value: str) -> str:
        allowed = {"percentage", "fixed", "free_shipping", "gift"}
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise ValueError(f"discount_type invalide: {value}")
        return normalized


class CouponPayload(BaseModel):
    promotion_id: int | None = None
    code: str | None = Field(None, max_length=64)
    coupon_kind: str = Field(default="multi", max_length=20)
    max_redemptions: int | None = Field(None, ge=1)
    per_customer_limit: int | None = Field(None, ge=1)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool = True
    config: dict | None = None
    quantity: int = Field(default=1, ge=1, le=200)

    @field_validator("coupon_kind")
    @classmethod
    def validate_coupon_kind(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"single", "multi"}:
            raise ValueError("coupon_kind invalide")
        return normalized


class PreviewItemPayload(BaseModel):
    product_id: int | None = None
    name: str
    qty: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(..., ge=0)
    category: str | None = None
    tax_category: str | None = None
    brand: str | None = None
    is_tax_exempt: bool = False


class PreviewRequest(BaseModel):
    items: list[PreviewItemPayload]
    coupon_codes: list[str] | None = None
    country_code: str | None = Field(None, min_length=2, max_length=2)
    channel: str | None = Field(default="manual")
    customer_id: int | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    customer_name: str | None = None
    event_context: dict | None = None


class RecommendationRequest(BaseModel):
    customer_id: int | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    channel: str | None = None
    country_code: str | None = Field(None, min_length=2, max_length=2)
    trigger_type: str | None = Field(None, max_length=50)


async def _load_store(db: AsyncSession, store_id: int) -> Store:
    store = await db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Store introuvable")
    return store


@router.get("/campaigns")
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    rows = (
        await db.execute(
            select(Campaign).where(Campaign.store_id == store_id).order_by(Campaign.created_at.desc(), Campaign.id.desc())
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "channel": row.channel,
                "trigger_type": row.trigger_type,
                "status": row.status,
                "start_at": row.start_at.isoformat() if row.start_at else None,
                "end_at": row.end_at.isoformat() if row.end_at else None,
                "config": row.config,
            }
            for row in rows
        ]
    }


@router.post("/campaigns", status_code=201)
async def create_campaign(body: CampaignPayload, db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    row = Campaign(store_id=store_id, **body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "status": "created"}


@router.get("/")
async def list_promotions(db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    rows = (
        await db.execute(
            select(Promotion).where(Promotion.store_id == store_id).order_by(Promotion.priority.asc(), Promotion.id.desc())
        )
    ).scalars().all()
    rules = (
        await db.execute(
            select(PromotionRule).where(PromotionRule.store_id == store_id).order_by(PromotionRule.priority.asc(), PromotionRule.id.asc())
        )
    ).scalars().all()
    rule_map: dict[int, list[dict]] = {}
    for rule in rules:
        rule_map.setdefault(int(rule.promotion_id), []).append(
            {
                "id": rule.id,
                "name": rule.name,
                "rule_type": rule.rule_type,
                "conditions": rule.conditions,
                "is_active": rule.is_active,
                "priority": rule.priority,
            }
        )
    return {
        "items": [
            {
                "id": row.id,
                "campaign_id": row.campaign_id,
                "name": row.name,
                "description": row.description,
                "promotion_type": row.promotion_type,
                "discount_type": row.discount_type,
                "discount_value": float(row.discount_value) if row.discount_value is not None else None,
                "applies_to": row.applies_to,
                "eligible_product_ids": row.eligible_product_ids,
                "eligible_categories": row.eligible_categories,
                "eligible_brands": row.eligible_brands,
                "gift_product_id": row.gift_product_id,
                "gift_name": row.gift_name,
                "gift_quantity": row.gift_quantity,
                "priority": row.priority,
                "stackable": row.stackable,
                "start_at": row.start_at.isoformat() if row.start_at else None,
                "end_at": row.end_at.isoformat() if row.end_at else None,
                "customer_segment": row.customer_segment,
                "country_codes": row.country_codes,
                "channel_codes": row.channel_codes,
                "max_global_uses": row.max_global_uses,
                "max_uses_per_customer": row.max_uses_per_customer,
                "max_discount_amount": float(row.max_discount_amount) if row.max_discount_amount is not None else None,
                "is_active": row.is_active,
                "config": row.config,
                "rules": rule_map.get(int(row.id), []),
            }
            for row in rows
        ]
    }


@router.post("/", status_code=201)
async def create_promotion(body: PromotionPayload, db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    if body.campaign_id is not None:
        campaign = await db.get(Campaign, body.campaign_id)
        if campaign is None or campaign.store_id != store_id:
            raise HTTPException(status_code=404, detail="Campaign introuvable")

    payload = body.model_dump(exclude={"rules"})
    row = Promotion(store_id=store_id, **payload)
    db.add(row)
    await db.flush()
    for rule in body.rules:
        db.add(PromotionRule(store_id=store_id, promotion_id=row.id, **rule.model_dump()))
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "status": "created"}


@router.get("/coupons")
async def list_coupons(db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    rows = (
        await db.execute(
            select(Coupon).where(Coupon.store_id == store_id).order_by(Coupon.created_at.desc(), Coupon.id.desc())
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": row.id,
                "promotion_id": row.promotion_id,
                "code": row.code,
                "coupon_kind": row.coupon_kind,
                "max_redemptions": row.max_redemptions,
                "redemptions_count": row.redemptions_count,
                "per_customer_limit": row.per_customer_limit,
                "starts_at": row.starts_at.isoformat() if row.starts_at else None,
                "ends_at": row.ends_at.isoformat() if row.ends_at else None,
                "is_active": row.is_active,
                "config": row.config,
            }
            for row in rows
        ]
    }


@router.post("/coupons", status_code=201)
async def create_coupon(body: CouponPayload, db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    if body.promotion_id is not None:
        promotion = await db.get(Promotion, body.promotion_id)
        if promotion is None or promotion.store_id != store_id:
            raise HTTPException(status_code=404, detail="Promotion introuvable")

    codes: list[str] = []
    base_code = (body.code or "PROMO").strip().upper()
    for idx in range(body.quantity):
        code = base_code if body.quantity == 1 and idx == 0 else f"{base_code}-{uuid4().hex[:8].upper()}"
        codes.append(code)
        db.add(
            Coupon(
                store_id=store_id,
                promotion_id=body.promotion_id,
                code=code,
                coupon_kind=body.coupon_kind,
                max_redemptions=1 if body.coupon_kind == "single" and body.max_redemptions is None else body.max_redemptions,
                per_customer_limit=body.per_customer_limit,
                starts_at=body.starts_at,
                ends_at=body.ends_at,
                is_active=body.is_active,
                config=body.config,
            )
        )
    await db.commit()
    return {"status": "created", "codes": codes}


@router.post("/preview")
async def preview_promotions(body: PreviewRequest, db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    store = await _load_store(db, store_id)
    items = [item.model_dump() for item in body.items]
    promo_result = await apply_promotions_to_items(
        db,
        store=store,
        items=items,
        coupon_codes=body.coupon_codes,
        country_code=body.country_code,
        channel=body.channel,
        customer_id=body.customer_id,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        customer_name=body.customer_name,
        event_context=body.event_context,
    )
    tax_result = await calculate_taxes_for_items(
        db=db,
        store=store,
        items=promo_result.items,
        country_code=body.country_code,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
    )
    return {
        "items": promo_result.items,
        "discount_amount": float(promo_result.discount_amount),
        "applied_promotions": promo_result.applied_promotions,
        "applied_coupon_codes": promo_result.applied_coupon_codes,
        "pricing": tax_result.as_dict(),
    }


@router.post("/recommendations")
async def smart_recommendations(body: RecommendationRequest, db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    store = await _load_store(db, store_id)
    items = await generate_smart_recommendations(
        db,
        store=store,
        customer_id=body.customer_id,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        channel=body.channel,
        country_code=body.country_code,
        trigger_type=(body.trigger_type or "").strip().lower() or None,
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "items": items,
    }
