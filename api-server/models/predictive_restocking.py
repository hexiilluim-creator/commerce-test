"""
models/predictive_restocking.py — Plan E2 — Predictive Restocking.

Tables:
  - restock_forecast      : daily forecasted demand per variant
  - restock_alert         : predicted stock-out / overstock / anomaly
  - restock_suggestion    : human-validated replenishment action
  - restock_seasonality   : per-SKU seasonal pattern snapshot
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base


class RestockAlertSeverity(enum.StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RestockAlertStatus(enum.StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SNOOZED = "snoozed"


class RestockSuggestionStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ORDERED = "ordered"
    RECEIVED = "received"


class RestockForecast(Base):
    __tablename__ = "restock_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    variant_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    sku: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    forecast_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    predicted_qty: Mapped[float] = mapped_column(Float, nullable=False)
    lower_bound: Mapped[float] = mapped_column(Float, nullable=False)
    upper_bound: Mapped[float] = mapped_column(Float, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_restock_forecasts_store_sku_date", "store_id", "sku", "forecast_date"),
    )


class RestockAlert(Base):
    __tablename__ = "restock_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    variant_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    sku: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)  # stockout|overstock|anomaly
    severity: Mapped[str] = mapped_column(
        SAEnum(RestockAlertSeverity, name="restock_alert_severity"),
        default=RestockAlertSeverity.MEDIUM,
    )
    status: Mapped[str] = mapped_column(
        SAEnum(RestockAlertStatus, name="restock_alert_status"),
        default=RestockAlertStatus.OPEN,
        index=True,
    )
    predicted_stockout_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    on_hand: Mapped[float | None] = mapped_column(Float, nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RestockSuggestion(Base):
    __tablename__ = "restock_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    variant_id: Mapped[int] = mapped_column(ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True)
    sku: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7)
    unit_cost: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum(RestockSuggestionStatus, name="restock_suggestion_status"),
        default=RestockSuggestionStatus.PENDING,
        index=True,
    )
    reviewer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RestockSeasonality(Base):
    __tablename__ = "restock_seasonality"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    sku: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    weekly_profile: Mapped[dict | None] = mapped_column(JSON, default=dict)   # {0..6: float}
    monthly_profile: Mapped[dict | None] = mapped_column(JSON, default=dict)  # {1..12: float}
    yearly_profile: Mapped[dict | None] = mapped_column(JSON, default=dict)  # {1..12: float} monthly-of-year
    trend_slope: Mapped[float] = mapped_column(Float, default=0.0)
    residual_std: Mapped[float] = mapped_column(Float, default=0.0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
