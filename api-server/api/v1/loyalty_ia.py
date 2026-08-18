"""api/v1/loyalty_ia.py — Plan E3 routes."""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import get_store_id, require_feature, require_role
from models.database import get_db
from models.loyalty_ia import (
    CustomerSegmentMember,
    LoyaltyChurnScore,
    LoyaltyIAModelVersion,
    LoyaltyRecommendation,
    ModelState,
    SegmentDefinition,
    SegmentType,
)
from services.loyalty_ia_service import (
    compute_rfm,
    personalize_reward,
    predict_churn,
    recommend_products,
    stable_model_version,
)

router = APIRouter(prefix="/loyalty-ia", tags=["Plan E — Loyalty IA"], dependencies=[require_feature("loyalty_ia")])


# ─── Schemas ────────────────────────────────────────────────────────────────


class SegmentIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=1000)
    segment_type: SegmentType = SegmentType.RFM
    rules: dict = Field(default_factory=dict)
    color: str | None = Field(None, max_length=16, pattern=r"^#[0-9A-Fa-f]{6}$")


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    store_id: int
    name: str
    description: str | None
    segment_type: str
    rules: dict
    color: str | None
    is_active: bool
    created_at: datetime


class RecommendIn(BaseModel):
    customer_purchase_skus: list[str] = Field(default_factory=list, max_length=200)
    cooccurrence: dict[str, dict[str, int]] = Field(default_factory=dict)
    catalog_skus: list[str] = Field(default_factory=list, max_length=2000)
    out_of_stock: list[str] = Field(default_factory=list, max_length=2000)
    top_n: int = Field(5, ge=1, le=50)
    customer_id: int | None = None


class PersonalizeIn(BaseModel):
    customer_id: int
    orders: list[tuple[datetime, float]] = Field(default_factory=list)
    eligible_rewards: list[dict] = Field(default_factory=list)
    cooldown_per_kind: dict[str, int] = Field(default_factory=dict)
    last_rewards_by_kind: dict[str, datetime] = Field(default_factory=dict)

    @field_validator("orders", mode="before")
    @classmethod
    def _coerce_orders(cls, v):
        if not isinstance(v, list | tuple):
            return []
        out = []
        for item in v:
            if isinstance(item, dict):
                d = datetime.fromisoformat(str(item["at"]).replace("Z", "+00:00"))
                out.append((d, float(item["total"])))
            elif isinstance(item, list | tuple) and len(item) == 2:
                dt_val = item[0]
                if isinstance(dt_val, str):
                    dt_val = datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
                out.append((dt_val, float(item[1])))
        return out


class ChurnIn(BaseModel):
    customer_id: int
    orders: list[tuple[datetime, float]] = Field(default_factory=list)
    days_since_last_reward: int = 0
    support_tickets_30d: int = 0
    avg_orders_per_month: float = 0.0

    @field_validator("orders", mode="before")
    @classmethod
    def _coerce_orders(cls, v):
        out = []
        for item in v or []:
            if isinstance(item, dict):
                d = datetime.fromisoformat(str(item["at"]).replace("Z", "+00:00"))
                out.append((d, float(item["total"])))
            elif isinstance(item, list | tuple) and len(item) == 2:
                dt_val = item[0]
                if isinstance(dt_val, str):
                    dt_val = datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
                out.append((dt_val, float(item[1])))
        return out


class ChurnOut(BaseModel):
    customer_id: int
    score: float
    risk_band: str
    drivers: dict


class ModelVersionIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    version: str = Field(..., min_length=1, max_length=32)
    params: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)


class ModelVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    version: str
    state: str
    metrics: dict
    params: dict
    promoted_at: datetime | None
    promoted_by: int | None
    created_at: datetime


# ─── Routes ─────────────────────────────────────────────────────────────────


@router.post("/segments", response_model=SegmentOut, dependencies=[require_role("manager")])
async def create_segment(payload: SegmentIn, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    seg = SegmentDefinition(
        store_id=store_id,
        name=payload.name,
        description=payload.description,
        segment_type=payload.segment_type,
        rules=payload.rules,
        color=payload.color,
        is_active=True,
    )
    session.add(seg)
    await session.commit()
    await session.refresh(seg)
    return SegmentOut.model_validate(seg)


@router.get("/simple")
async def get_loyalty_simple(
    store_id: int = Depends(get_store_id),
    db: AsyncSession = Depends(get_db),
):
    """Vue simplifiée fidélisation — pensée pour un marchand, pas un développeur.

    AUDIT FIX (retour utilisateur) : la page Loyalty IA était uniquement un
    outil de test technique (Model Registry, clients fictifs codés en dur,
    JSON brut). Cet endpoint lit les VRAIS clients/commandes déjà en base
    (aucune nouvelle table, aucune migration), calcule un statut simple par
    client (fidèle / à relancer / perdu) via la même logique RFM déjà
    existante (compute_rfm), et fournit tout ce qu'il faut pour proposer une
    action de relance simple côté frontend (lien WhatsApp direct — pas de
    nouvelle table de messages, pas de nouvel envoi automatisé).
    """
    from models.database import Customer, Order

    result = await db.execute(
        select(Customer).where(Customer.store_id == store_id, Customer.opted_out.is_(False))
    )
    customers = result.scalars().all()

    now = datetime.now(UTC)
    items = []
    for customer in customers:
        orders_result = await db.execute(
            select(Order.created_at, Order.total_amount)
            .where(Order.store_id == store_id, Order.customer_id == customer.id)
        )
        orders = orders_result.all()
        if not orders:
            continue  # pas encore de client réel, rien à afficher

        rfm = compute_rfm(
            customer.id,
            [(o.created_at, float(o.total_amount)) for o in orders],
            now=now,
        )

        if rfm.recency_days <= 30 and rfm.frequency >= 2:
            status = "fidele"
        elif rfm.recency_days <= 90:
            status = "a_relancer"
        else:
            status = "perdu"

        items.append({
            "customer_id": customer.id,
            "name": customer.name or customer.whatsapp_phone,
            "whatsapp_phone": customer.whatsapp_phone,
            "last_order_days_ago": rfm.recency_days,
            "total_orders": rfm.frequency,
            "total_spent": round(rfm.monetary, 3),
            "status": status,
        })

    # Priorité d'affichage : les clients à relancer/perdus en premier —
    # ce sont ceux qui bénéficient le plus d'une action.
    order_priority = {"perdu": 0, "a_relancer": 1, "fidele": 2}
    items.sort(key=lambda it: (order_priority[it["status"]], -it["last_order_days_ago"]))
    return {"customers": items}


@router.get("/segments", response_model=list[SegmentOut])
async def list_segments(session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    res = await session.execute(
        select(SegmentDefinition)
        .where(SegmentDefinition.store_id == store_id)
        .order_by(SegmentDefinition.created_at.desc())
    )
    return [SegmentOut.model_validate(s) for s in res.scalars().all()]


@router.post("/rfm")
async def rfm(payload: PersonalizeIn):
    rfm_res = compute_rfm(payload.customer_id, [(d, t) for d, t in payload.orders])
    return {"customer_id": payload.customer_id, "rfm": rfm_res.__dict__}


@router.post("/recommend")
async def recommend(payload: RecommendIn, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    out = recommend_products(
        customer_purchase_skus=payload.customer_purchase_skus,
        cooccurrence={k: {kk: int(vv) for kk, vv in (v or {}).items()} for k, v in payload.cooccurrence.items()},
        catalog_skus=payload.catalog_skus,
        out_of_stock=set(payload.out_of_stock),
        top_n=payload.top_n,
    )
    # Persist (best-effort, no score on existing rows conflicting).
    if payload.customer_id is not None:
        version = stable_model_version("recommend", {"top_n": payload.top_n})
        for rec in out:
            session.add(
                LoyaltyRecommendation(
                    store_id=store_id,
                    customer_id=payload.customer_id,
                    sku=rec["sku"],
                    score=rec["score"],
                    reason="co_occurrence",
                    model_version=version,
                )
            )
        await session.commit()
    return {"recommendations": out}


@router.post("/personalize")
async def personalize(payload: PersonalizeIn):
    rfm_res = compute_rfm(payload.customer_id, payload.orders)
    best = personalize_reward(
        rfm=rfm_res,
        eligible_rewards=payload.eligible_rewards,
        cooldown_per_kind=payload.cooldown_per_kind,
        last_rewards_by_kind=payload.last_rewards_by_kind,
    )
    return {"rfm_segment": rfm_res.segment, "reward": best}


@router.post("/churn", response_model=ChurnOut)
async def churn(payload: ChurnIn, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    rfm_res = compute_rfm(payload.customer_id, payload.orders)
    score, band, drivers = predict_churn(
        rfm=rfm_res,
        days_since_last_reward=payload.days_since_last_reward,
        support_tickets_30d=payload.support_tickets_30d,
        avg_orders_per_month=payload.avg_orders_per_month,
    )
    version = stable_model_version("churn", {})
    session.add(
        LoyaltyChurnScore(
            store_id=store_id,
            customer_id=payload.customer_id,
            score=score,
            risk_band=band,
            drivers=drivers,
            model_version=version,
        )
    )
    await session.commit()
    return ChurnOut(customer_id=payload.customer_id, score=score, risk_band=band, drivers=drivers)


@router.post("/churn/bulk")
async def churn_bulk(payload: list[ChurnIn], session: AsyncSession = Depends(get_db)):
    """Compute churn for many customers in one round-trip (UI heatmap payload)."""
    get_store_id()
    out = []
    for item in payload:
        rfm_res = compute_rfm(item.customer_id, item.orders)
        score, band, drivers = predict_churn(
            rfm=rfm_res,
            days_since_last_reward=item.days_since_last_reward,
            support_tickets_30d=item.support_tickets_30d,
            avg_orders_per_month=item.avg_orders_per_month,
        )
        out.append({"customer_id": item.customer_id, "score": score, "risk_band": band, "drivers": drivers})
    return {"results": out, "model_version": stable_model_version("churn", {"n": len(payload)})}


@router.post("/models", response_model=ModelVersionOut, dependencies=[require_role("admin")])
async def register_model_version(payload: ModelVersionIn, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    row = LoyaltyIAModelVersion(
        store_id=store_id,
        name=payload.name,
        version=payload.version,
        state=ModelState.CANDIDATE,
        metrics=payload.metrics,
        params=payload.params,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ModelVersionOut.model_validate(row)


@router.post("/models/{model_id}/promote", response_model=ModelVersionOut, dependencies=[require_role("admin")])
async def promote(model_id: int, request: Request, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    res = await session.execute(
        select(LoyaltyIAModelVersion).where(
            LoyaltyIAModelVersion.id == model_id,
            LoyaltyIAModelVersion.store_id == store_id,
        )
    )
    model = res.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    # Demote peer models with the same name in the same store.
    peers = await session.execute(
        select(LoyaltyIAModelVersion).where(
            LoyaltyIAModelVersion.store_id == store_id,
            LoyaltyIAModelVersion.name == model.name,
            LoyaltyIAModelVersion.id != model.id,
        )
    )
    for peer in peers.scalars().all():
        if peer.state == ModelState.PRODUCTION:
            peer.state = ModelState.ARCHIVED
    model.state = ModelState.PRODUCTION
    model.promoted_at = datetime.now(UTC)
    reviewer_id = getattr(request.state.jwt_payload, "get", lambda *_: None)("user_id") or 0
    model.promoted_by = int(reviewer_id)
    await session.commit()
    await session.refresh(model)
    return ModelVersionOut.model_validate(model)


@router.get("/models", response_model=list[ModelVersionOut])
async def list_models(session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    res = await session.execute(
        select(LoyaltyIAModelVersion)
        .where(LoyaltyIAModelVersion.store_id == store_id)
        .order_by(LoyaltyIAModelVersion.created_at.desc())
    )
    return [ModelVersionOut.model_validate(m) for m in res.scalars().all()]
