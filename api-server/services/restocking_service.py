"""
services/restocking_service.py — Plan E2 — Predictive Restocking.

Stateless service: pure functions over already-aggregated sales data plus
deterministic, well-known baselines (Holt-Winters-lite, FFT-lite, EOQ).

For dev/test: a `seed_restocking_demo` helper creates a tiny synthetic
sales series so the UI / API are demonstrable end-to-end without a real
catalog or order history.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.predictive_restocking import (
    RestockAlert,
    RestockAlertSeverity,
    RestockAlertStatus,
    RestockForecast,
    RestockSeasonality,
    RestockSuggestion,
    RestockSuggestionStatus,
)

# ─── Pure helpers ───────────────────────────────────────────────────────────

def holt_winters_forecast(series: list[float], horizon: int, alpha: float = 0.3,
                          beta: float = 0.1, season_len: int = 7) -> list[float]:
    """Tiny linear-trend + seasonal-naive hybrid. Handles short series
    gracefully (< season_len) by falling back to a moving average."""
    if not series:
        return [0.0] * horizon
    if len(series) < season_len:
        window = max(1, len(series) // 2 or 1)
        avg = sum(series[-window:]) / window
        return [avg] * horizon
    season = [series[i] for i in range(-season_len, 0)]
    level = sum(series[:season_len]) / season_len
    trend = (sum(series[season_len:2 * season_len]) - sum(series[:season_len])) / (season_len ** 2)
    forecast: list[float] = []
    for h in range(1, horizon + 1):
        s = season[(h - 1) % season_len]
        yhat = max(0.0, (level + h * trend) * s / max(1e-6, level))
        forecast.append(yhat)
        level = level + alpha * (yhat - level)
        trend = trend + beta * ((level - trend) - trend)
    return forecast


def confidence_band(point: list[float], residual_std: float, z: float = 1.96) -> tuple[list[float], list[float]]:
    return ([max(0.0, y - z * residual_std) for y in point],
            [y + z * residual_std for y in point])


def fft_lite_seasonality(series: list[float], period: int) -> dict[int, float]:
    """Returns averaged buckets (1..period) each as a multiplier vs mean."""
    if not series or period <= 0:
        return {i: 1.0 for i in range(1, period + 1)}
    buckets: list[list[float]] = [[] for _ in range(period)]
    for i, v in enumerate(series):
        buckets[i % period].append(v)
    means = [statistics.mean(b) if b else 0.0 for b in buckets]
    overall = statistics.mean(means) or 1.0
    return {i + 1: (m / overall if overall else 1.0) for i, m in enumerate(means)}


def linear_trend(series: list[float]) -> float:
    n = len(series)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(series) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, series, strict=False))
    den = sum((x - x_mean) ** 2 for x in xs) or 1e-9
    return num / den


def residual_std(series: list[float]) -> float:
    if len(series) < 3:
        return 0.0
    n = len(series)
    trend = linear_trend(series)
    intercept = sum(series) / n - trend * ((n - 1) / 2)
    diffs = [y - (intercept + trend * i) for i, y in enumerate(series)]
    return statistics.pstdev(diffs)


def safety_stock(avg_daily: float, lead_days: int, service_z: float = 1.65) -> float:
    sd = max(1.0, residual_std([avg_daily] * max(7, lead_days)))  # guard for flat series
    return service_z * sd * math.sqrt(max(1, lead_days))


def eoq(annual_demand: float, order_cost: float = 25.0, holding_cost: float = 0.1) -> float:
    if annual_demand <= 0 or holding_cost <= 0:
        return 0.0
    return math.sqrt((2 * annual_demand * order_cost) / holding_cost)


# ─── Service calls (DB-aware) ──────────────────────────────────────────────

@dataclass
class ForecastResult:
    sku: str
    horizon_days: int
    daily: list[float]
    lower: list[float]
    upper: list[float]
    model_version: str


async def forecast_demand(
    session: AsyncSession,
    *,
    store_id: int,
    sku: str,
    history: list[tuple[date, float]],
    horizon: int = 30,
    model_version: str = "hw-lite-v1",
) -> ForecastResult:
    history = sorted(history, key=lambda x: x[0])
    series = [q for _, q in history]
    point = holt_winters_forecast(series, horizon)
    lower, upper = confidence_band(point, residual_std(series) or (statistics.pstdev(series) if len(series) > 1 else 0.1))
    today = date.today()
    for i, (q, lo, hi) in enumerate(zip(point, lower, upper, strict=False)):
        session.add(RestockForecast(
            store_id=store_id,
            sku=sku,
            forecast_date=today + timedelta(days=i + 1),
            horizon_days=horizon,
            predicted_qty=q,
            lower_bound=lo,
            upper_bound=hi,
            model_version=model_version,
        ))
    await session.flush()
    return ForecastResult(sku=sku, horizon_days=horizon, daily=point, lower=lower,
                          upper=upper, model_version=model_version)


async def detect_seasonality(
    session: AsyncSession,
    *,
    store_id: int,
    sku: str,
    history: list[tuple[date, float]],
) -> RestockSeasonality:
    history = sorted(history, key=lambda x: x[0])
    series = [q for _, q in history]
    weekly = fft_lite_seasonality(series, 7)
    monthly = fft_lite_seasonality(series, 30)
    yearly = fft_lite_seasonality(series, max(7, len(series) // 2))
    row = RestockSeasonality(
        store_id=store_id,
        sku=sku,
        weekly_profile=weekly,
        monthly_profile=monthly,
        yearly_profile=yearly,
        trend_slope=linear_trend(series),
        residual_std=residual_std(series),
    )
    session.add(row)
    await session.flush()
    return row


async def suggest_replenishment(
    session: AsyncSession,
    *,
    store_id: int,
    sku: str,
    avg_daily: float,
    lead_time_days: int,
    on_hand: float,
    unit_cost: float | None = None,
    annual_demand: float | None = None,
) -> RestockSuggestion:
    target = avg_daily * lead_time_days + safety_stock(avg_daily, lead_time_days)
    qty = max(0.0, round(target - on_hand, 2))
    if annual_demand and unit_cost:
        qty = max(qty, round(eoq(annual_demand / unit_cost), 0))
    sugg = RestockSuggestion(
        store_id=store_id,
        sku=sku,
        qty=qty,
        lead_time_days=lead_time_days,
        unit_cost=unit_cost,
        rationale=f"avg_daily={avg_daily:.2f}, lead={lead_time_days}d, on_hand={on_hand:.2f}",
        status=RestockSuggestionStatus.PENDING,
    )
    session.add(sugg)
    await session.flush()
    return sugg


async def approve_suggestion(
    session: AsyncSession,
    *,
    suggestion: RestockSuggestion,
    reviewer_id: int,
    note: str | None = None,
) -> RestockSuggestion:
    if suggestion.status != RestockSuggestionStatus.PENDING:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Suggestion is not pending")
    suggestion.status = RestockSuggestionStatus.APPROVED
    suggestion.reviewer_id = reviewer_id
    suggestion.reviewed_at = datetime.now(UTC)
    suggestion.review_note = note
    await session.flush()
    return suggestion


async def raise_alert(
    session: AsyncSession,
    *,
    store_id: int,
    sku: str,
    alert_type: str,
    severity: RestockAlertSeverity,
    predicted_stockout_date: date | None,
    on_hand: float,
    lead_time_days: int,
    payload: dict | None = None,
) -> RestockAlert:
    alert = RestockAlert(
        store_id=store_id,
        sku=sku,
        alert_type=alert_type,
        severity=severity,
        status=RestockAlertStatus.OPEN,
        predicted_stockout_date=predicted_stockout_date,
        on_hand=on_hand,
        lead_time_days=lead_time_days,
        payload=payload or {},
    )
    session.add(alert)
    await session.flush()
    return alert


# ─── Demo seeder (deterministic synthetic series for the dev UI) ───────────

async def seed_restocking_demo(session: AsyncSession, store_id: int, sku: str = "DEMO-001") -> dict:
    """Generate a 60-day synthetic series and run the full pipeline once.
    Returns a summary dict for the UI / tests to assert on."""
    import random
    rng = random.Random(f"{sku}:{store_id}")
    today = date.today()
    series: list[tuple[date, float]] = []
    base = 8.0
    for i in range(60):
        dow = (today - timedelta(days=59 - i)).weekday()
        weekly = 1.0 + 0.4 * math.sin((dow / 7.0) * 2 * math.pi)
        noise = rng.uniform(-0.6, 0.6) * 2
        series.append((today - timedelta(days=59 - i), max(0.0, base * weekly + noise)))

    fc = await forecast_demand(session, store_id=store_id, sku=sku, history=series, horizon=14)
    season = await detect_seasonality(session, store_id=store_id, sku=sku, history=series)
    sugg = await suggest_replenishment(
        session, store_id=store_id, sku=sku,
        avg_daily=sum(q for _, q in series) / max(1, len(series)),
        lead_time_days=7,
        on_hand=10.0,
    )
    if sugg.qty > 0:
        await raise_alert(
            session, store_id=store_id, sku=sku, alert_type="stockout",
            severity=RestockAlertSeverity.MEDIUM,
            predicted_stockout_date=today + timedelta(days=5),
            on_hand=10.0, lead_time_days=7,
            payload={"suggestion_id": sugg.id},
        )
    return {
        "sku": sku,
        "forecast_first": fc.daily[0] if fc.daily else 0.0,
        "weekly_profile_keys": list((season.weekly_profile or {}).keys()),
        "suggestion_qty": float(sugg.qty),
    }
