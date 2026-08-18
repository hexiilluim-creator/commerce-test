"""api/v1/predictive_restocking.py — Plan E2 routes."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import get_store_id, require_feature, require_role
from models.database import get_db
from models.predictive_restocking import (
    RestockAlert,
    RestockAlertSeverity,
    RestockAlertStatus,
    RestockForecast,
    RestockSeasonality,
    RestockSuggestion,
    RestockSuggestionStatus,
)
from services.restocking_service import (
    approve_suggestion as svc_approve,
)
from services.restocking_service import (
    detect_seasonality as svc_season,
)
from services.restocking_service import (
    forecast_demand as svc_forecast,
)
from services.restocking_service import (
    raise_alert as svc_alert,
)
from services.restocking_service import (
    seed_restocking_demo as svc_seed_demo,
)
from services.restocking_service import (
    suggest_replenishment as svc_suggest,
)

router = APIRouter(prefix="/restocking", tags=["Plan E — Predictive Restocking"], dependencies=[require_feature("restocking")])


# ─── Schemas ────────────────────────────────────────────────────────────────

class HistoryPoint(BaseModel):
    d: date
    qty: float


class ForecastIn(BaseModel):
    sku: str = Field(..., min_length=1, max_length=80)
    horizon: int = Field(30, ge=1, le=180)
    history: list[HistoryPoint] = Field(default_factory=list, max_length=730)


class SuggestIn(BaseModel):
    sku: str = Field(..., min_length=1, max_length=80)
    avg_daily: float = Field(..., ge=0)
    lead_time_days: int = Field(7, ge=1, le=120)
    on_hand: float = Field(0, ge=0)
    unit_cost: float | None = None
    annual_demand: float | None = None


class AlertIn(BaseModel):
    sku: str = Field(..., min_length=1, max_length=80)
    alert_type: str = Field("stockout", pattern="^(stockout|overstock|anomaly)$")
    severity: RestockAlertSeverity = RestockAlertSeverity.MEDIUM
    predicted_stockout_date: date | None = None
    on_hand: float = 0
    lead_time_days: int = 7
    payload: dict = Field(default_factory=dict)


class ApproveIn(BaseModel):
    note: str | None = Field(None, max_length=2000)


class ForecastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sku: str
    forecast_date: date
    horizon_days: int
    predicted_qty: float
    lower_bound: float
    upper_bound: float
    model_version: str
    computed_at: datetime


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sku: str
    alert_type: str
    severity: str
    status: str
    predicted_stockout_date: date | None
    on_hand: float | None
    lead_time_days: int | None
    payload: dict | None
    created_at: datetime


class SuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sku: str
    qty: float
    supplier: str | None
    lead_time_days: int
    unit_cost: float | None
    rationale: str | None
    status: str
    reviewer_id: int | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime


class SeasonalityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    sku: str
    weekly_profile: dict | None
    monthly_profile: dict | None
    yearly_profile: dict | None
    trend_slope: float
    residual_std: float
    computed_at: datetime | None


# ─── helpers ────────────────────────────────────────────────────────────────

async def _load_suggestion(session: AsyncSession, store_id: int, suggestion_id: int) -> RestockSuggestion:
    res = await session.execute(
        select(RestockSuggestion).where(
            RestockSuggestion.id == suggestion_id,
            RestockSuggestion.store_id == store_id,
        )
    )
    s = res.scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Suggestion introuvable")
    return s


# ─── Routes ─────────────────────────────────────────────────────────────────

@router.post("/forecast", dependencies=[require_role("manager")])
async def forecast(payload: ForecastIn, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    history = [(p.d, float(p.qty)) for p in payload.history]
    res = await svc_forecast(
        session, store_id=store_id, sku=payload.sku,
        history=history, horizon=payload.horizon,
    )
    await session.commit()
    return {
        "sku": res.sku,
        "horizon_days": res.horizon_days,
        "model_version": res.model_version,
        "daily": res.daily,
        "lower": res.lower,
        "upper": res.upper,
    }


@router.post("/seasonality", response_model=SeasonalityOut, dependencies=[require_role("manager")])
async def seasonality(payload: ForecastIn, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    history = [(p.d, float(p.qty)) for p in payload.history]
    row = await svc_season(session, store_id=store_id, sku=payload.sku, history=history)
    await session.commit()
    return SeasonalityOut.model_validate(row)


@router.post("/suggest", response_model=SuggestionOut, dependencies=[require_role("manager")])
async def suggest(payload: SuggestIn, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    sugg = await svc_suggest(
        session,
        store_id=store_id,
        sku=payload.sku,
        avg_daily=payload.avg_daily,
        lead_time_days=payload.lead_time_days,
        on_hand=payload.on_hand,
        unit_cost=payload.unit_cost,
        annual_demand=payload.annual_demand,
    )
    await session.commit()
    await session.refresh(sugg)
    return SuggestionOut.model_validate(sugg)


@router.post("/{suggestion_id}/approve", response_model=SuggestionOut,
             dependencies=[require_role("admin")])
async def approve(suggestion_id: int, payload: ApproveIn,
                  request: Request, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    sugg = await _load_suggestion(session, store_id, suggestion_id)
    if sugg.status not in {RestockSuggestionStatus.PENDING}:
        raise HTTPException(status_code=409, detail="Seules les suggestions 'pending' peuvent être approuvées")
    reviewer_id = getattr(request.state.jwt_payload, "get", lambda *_: None)("user_id") or 0
    await svc_approve(session, suggestion=sugg, reviewer_id=int(reviewer_id), note=payload.note)
    await session.commit()
    await session.refresh(sugg)
    return SuggestionOut.model_validate(sugg)


@router.post("/alert", response_model=AlertOut, dependencies=[require_role("manager")])
async def raise_alert(payload: AlertIn, session: AsyncSession = Depends(get_db)):
    store_id = get_store_id()
    a = await svc_alert(
        session,
        store_id=store_id,
        sku=payload.sku,
        alert_type=payload.alert_type,
        severity=payload.severity,
        predicted_stockout_date=payload.predicted_stockout_date,
        on_hand=payload.on_hand,
        lead_time_days=payload.lead_time_days,
        payload=payload.payload,
    )
    await session.commit()
    await session.refresh(a)
    return AlertOut.model_validate(a)


@router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(
    status: RestockAlertStatus | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
):
    store_id = get_store_id()
    stmt = select(RestockAlert).where(RestockAlert.store_id == store_id)
    if status:
        stmt = stmt.where(RestockAlert.status == status)
    stmt = stmt.order_by(RestockAlert.created_at.desc()).limit(limit)
    res = await session.execute(stmt)
    return [AlertOut.model_validate(a) for a in res.scalars().all()]


@router.get("/suggestions", response_model=list[SuggestionOut])
async def list_suggestions(
    status: RestockSuggestionStatus | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
):
    store_id = get_store_id()
    stmt = select(RestockSuggestion).where(RestockSuggestion.store_id == store_id)
    if status:
        stmt = stmt.where(RestockSuggestion.status == status)
    stmt = stmt.order_by(RestockSuggestion.created_at.desc()).limit(limit)
    res = await session.execute(stmt)
    return [SuggestionOut.model_validate(s) for s in res.scalars().all()]


@router.get("/forecasts", response_model=list[ForecastOut])
async def list_forecasts(
    sku: str | None = Query(None),
    horizon: int = Query(30, ge=1, le=180),
    limit: int = Query(100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
):
    store_id = get_store_id()
    stmt = select(RestockForecast).where(
        RestockForecast.store_id == store_id, RestockForecast.horizon_days == horizon
    )
    if sku:
        stmt = stmt.where(RestockForecast.sku == sku)
    stmt = stmt.order_by(RestockForecast.forecast_date.asc()).limit(limit)
    res = await session.execute(stmt)
    return [ForecastOut.model_validate(f) for f in res.scalars().all()]


@router.post("/seed-demo", dependencies=[require_role("admin")])
async def seed_demo(sku: str = "DEMO-001", session: AsyncSession = Depends(get_db)):
    """Deterministic end-to-end demo data for development & screenshots."""
    store_id = get_store_id()
    summary = await svc_seed_demo(session, store_id=store_id, sku=sku)
    await session.commit()
    return summary
