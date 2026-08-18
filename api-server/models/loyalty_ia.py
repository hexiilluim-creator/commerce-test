"""
models/loyalty_ia.py — Plan E3 — Loyalty IA.

Tables:
  - segment_definition       : rule-based segments (DSL in JSONB)
  - customer_segment_member  : materialized membership
  - loyalty_recommendation   : per-customer next-best suggestions
  - loyalty_churn_score      : per-customer churn score + drivers
  - loyalty_ia_model_version : versioned model registry
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base


class SegmentType(enum.StrEnum):
    RFM = "rfm"
    BEHAVIORAL = "behavioral"
    LIFECYCLE = "lifecycle"
    CUSTOM = "custom"


class ModelState(enum.StrEnum):
    CANDIDATE = "candidate"
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"


class SegmentDefinition(Base):
    __tablename__ = "segment_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    segment_type: Mapped[str] = mapped_column(
        SAEnum(SegmentType, name="segment_type"), default=SegmentType.RFM, nullable=False
    )
    rules: Mapped[dict] = mapped_column(JSON, default=dict)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("store_id", "name", name="uq_segment_name_per_store"),
    )


class CustomerSegmentMember(Base):
    __tablename__ = "customer_segment_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    segment_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    last_computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("store_id", "customer_id", "segment_id", name="uq_customer_segment"),
        Index("ix_csm_segment_score", "segment_id", "score"),
    )


class LoyaltyRecommendation(Base):
    __tablename__ = "loyalty_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    variant_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sku: Mapped[str | None] = mapped_column(String(80), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(String(255), default="co_occurrence")
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_lr_store_customer_score", "store_id", "customer_id", "score"),
    )


class LoyaltyChurnScore(Base):
    __tablename__ = "loyalty_churn_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)  # 0..1
    risk_band: Mapped[str] = mapped_column(String(16), default="medium")
    drivers: Mapped[dict] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_churn_band", "store_id", "risk_band"),
        Index("ix_churn_customer", "store_id", "customer_id"),
    )


class LoyaltyIAModelVersion(Base):
    __tablename__ = "loyalty_ia_model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(
        SAEnum(ModelState, name="loyalty_ia_model_state"),
        default=ModelState.CANDIDATE,
        nullable=False,
    )
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    promoted_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("store_id", "name", "version", name="uq_lia_model_version"),
    )
