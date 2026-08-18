"""tests/test_restocking_service.py — Tests pour services/restocking_service.py (Plan E2).

BUG#10 FIX: ce module (288 lignes) était à 0% de couverture de tests.
Combine fonctions pures (forecasting math) et fonctions DB-aware.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from models.database import Base
from models.predictive_restocking import RestockAlertSeverity, RestockSuggestionStatus
from services.restocking_service import (
    approve_suggestion,
    confidence_band,
    detect_seasonality,
    eoq,
    fft_lite_seasonality,
    forecast_demand,
    holt_winters_forecast,
    linear_trend,
    raise_alert,
    residual_std,
    safety_stock,
    seed_restocking_demo,
    suggest_replenishment,
)


@pytest_asyncio.fixture
async def rs_session():
    """Session SQLite in-memory isolée pour ce fichier de tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ─── holt_winters_forecast (pure) ─────────────────────────────────────────────

def test_holt_winters_forecast_happy_path():
    series = [10.0, 12.0, 11.0, 13.0, 14.0, 12.0, 15.0, 16.0, 14.0, 17.0, 18.0, 16.0, 19.0, 20.0]
    result = holt_winters_forecast(series, horizon=7)
    assert len(result) == 7
    assert all(v >= 0 for v in result)


def test_holt_winters_forecast_edge_case_empty_series():
    """Série vide → horizon de zéros, pas de crash."""
    result = holt_winters_forecast([], horizon=5)
    assert result == [0.0] * 5


def test_holt_winters_forecast_edge_case_short_series():
    """Série plus courte que season_len → fallback moyenne mobile."""
    result = holt_winters_forecast([5.0, 6.0, 7.0], horizon=3, season_len=7)
    assert len(result) == 3
    assert all(v >= 0 for v in result)


def test_holt_winters_forecast_invalid_input_zero_horizon():
    result = holt_winters_forecast([1.0, 2.0, 3.0], horizon=0)
    assert result == []


# ─── confidence_band (pure) ───────────────────────────────────────────────────

def test_confidence_band_happy_path():
    point = [10.0, 12.0, 15.0]
    lower, upper = confidence_band(point, residual_std=2.0)
    assert len(lower) == len(upper) == 3
    assert all(lo <= p <= up for lo, p, up in zip(lower, point, upper, strict=False))


def test_confidence_band_edge_case_zero_std():
    """Écart-type nul → bornes égales au point central."""
    point = [10.0, 12.0]
    lower, upper = confidence_band(point, residual_std=0.0)
    assert lower == point
    assert upper == point


def test_confidence_band_lower_never_negative():
    point = [1.0]
    lower, upper = confidence_band(point, residual_std=100.0)
    assert lower[0] >= 0.0  # clamped at zero


# ─── fft_lite_seasonality (pure) ──────────────────────────────────────────────

def test_fft_lite_seasonality_happy_path():
    series = [10.0, 5.0, 10.0, 5.0, 10.0, 5.0, 10.0, 5.0]
    result = fft_lite_seasonality(series, period=2)
    assert len(result) == 2
    assert all(isinstance(k, int) for k in result.keys())


def test_fft_lite_seasonality_edge_case_empty_series():
    result = fft_lite_seasonality([], period=7)
    assert len(result) == 7
    assert all(v == 1.0 for v in result.values())


def test_fft_lite_seasonality_invalid_input_zero_period():
    result = fft_lite_seasonality([1.0, 2.0], period=0)
    assert result == {}


# ─── linear_trend / residual_std (pure) ───────────────────────────────────────

def test_linear_trend_happy_path_increasing():
    series = [1.0, 2.0, 3.0, 4.0, 5.0]
    trend = linear_trend(series)
    assert trend > 0  # increasing series → positive trend


def test_linear_trend_edge_case_single_value():
    assert linear_trend([5.0]) == 0.0


def test_linear_trend_edge_case_empty():
    assert linear_trend([]) == 0.0


def test_residual_std_edge_case_short_series():
    """Moins de 3 points → 0.0 (pas assez de données pour un écart-type fiable)."""
    assert residual_std([1.0, 2.0]) == 0.0


# ─── safety_stock / eoq (pure) ────────────────────────────────────────────────

def test_safety_stock_happy_path():
    result = safety_stock(avg_daily=10.0, lead_days=7)
    assert result >= 0


def test_eoq_happy_path():
    result = eoq(annual_demand=1000.0, order_cost=25.0, holding_cost=0.1)
    assert result > 0


def test_eoq_invalid_input_zero_demand():
    """Demande annuelle nulle → EOQ = 0, pas de division par zéro."""
    assert eoq(annual_demand=0.0) == 0.0


def test_eoq_invalid_input_negative_holding_cost():
    assert eoq(annual_demand=100.0, holding_cost=-1.0) == 0.0


# ─── forecast_demand (DB-aware) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_forecast_demand_happy_path(rs_session):
    today = date.today()
    history = [(today - timedelta(days=i), 10.0 + i % 5) for i in range(30, 0, -1)]
    result = await forecast_demand(
        rs_session, store_id=1, sku="SKU-001", history=history, horizon=7
    )
    assert result.sku == "SKU-001"
    assert len(result.daily) == 7
    assert len(result.lower) == 7
    assert len(result.upper) == 7


@pytest.mark.asyncio
async def test_forecast_demand_edge_case_empty_history(rs_session):
    """Pas d'historique de ventes → forecast à zéro, pas de crash."""
    result = await forecast_demand(
        rs_session, store_id=1, sku="SKU-NEW", history=[], horizon=5
    )
    assert len(result.daily) == 5
    assert all(v == 0.0 for v in result.daily)


# ─── detect_seasonality (DB-aware) ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_seasonality_happy_path(rs_session):
    today = date.today()
    history = [(today - timedelta(days=i), float(10 + (i % 7))) for i in range(60, 0, -1)]
    result = await detect_seasonality(rs_session, store_id=1, sku="SKU-001", history=history)
    assert result.sku == "SKU-001"
    assert result.weekly_profile is not None


# ─── suggest_replenishment (DB-aware) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_suggest_replenishment_happy_path(rs_session):
    sugg = await suggest_replenishment(
        rs_session, store_id=1, sku="SKU-001",
        avg_daily=10.0, lead_time_days=7, on_hand=20.0,
    )
    assert sugg.status == RestockSuggestionStatus.PENDING
    assert sugg.qty >= 0


@pytest.mark.asyncio
async def test_suggest_replenishment_edge_case_high_stock(rs_session):
    """Stock déjà très élevé → quantité suggérée = 0 (pas négative)."""
    sugg = await suggest_replenishment(
        rs_session, store_id=1, sku="SKU-001",
        avg_daily=1.0, lead_time_days=1, on_hand=10000.0,
    )
    assert sugg.qty == 0.0


# ─── approve_suggestion (DB-aware) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_suggestion_happy_path(rs_session):
    sugg = await suggest_replenishment(
        rs_session, store_id=1, sku="SKU-001", avg_daily=10.0, lead_time_days=7, on_hand=5.0,
    )
    approved = await approve_suggestion(rs_session, suggestion=sugg, reviewer_id=42, note="OK")
    assert approved.status == RestockSuggestionStatus.APPROVED
    assert approved.reviewer_id == 42


@pytest.mark.asyncio
async def test_approve_suggestion_invalid_input_already_approved(rs_session):
    """Approuver une suggestion déjà traitée doit lever HTTPException 409."""
    from fastapi import HTTPException
    sugg = await suggest_replenishment(
        rs_session, store_id=1, sku="SKU-001", avg_daily=10.0, lead_time_days=7, on_hand=5.0,
    )
    await approve_suggestion(rs_session, suggestion=sugg, reviewer_id=1)
    with pytest.raises(HTTPException) as exc_info:
        await approve_suggestion(rs_session, suggestion=sugg, reviewer_id=2)
    assert exc_info.value.status_code == 409


# ─── raise_alert (DB-aware) ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_raise_alert_happy_path(rs_session):
    alert = await raise_alert(
        rs_session, store_id=1, sku="SKU-001", alert_type="stockout",
        severity=RestockAlertSeverity.HIGH,
        predicted_stockout_date=date.today() + timedelta(days=3),
        on_hand=2.0, lead_time_days=7,
    )
    assert alert.alert_type == "stockout"
    assert alert.severity == RestockAlertSeverity.HIGH


# ─── seed_restocking_demo (full pipeline integration) ────────────────────────

@pytest.mark.asyncio
async def test_seed_restocking_demo_happy_path(rs_session):
    """Test end-to-end du pipeline complet — forecast + seasonality + suggestion."""
    result = await seed_restocking_demo(rs_session, store_id=1, sku="DEMO-TEST")
    assert result["sku"] == "DEMO-TEST"
    assert "forecast_first" in result
    assert "suggestion_qty" in result
    assert result["suggestion_qty"] >= 0
