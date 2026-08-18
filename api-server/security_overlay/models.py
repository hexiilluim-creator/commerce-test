"""security_overlay/models.py — Modèles de données facturation SaaS.

Modèles de données facturation SaaS.
Dataclasses et ORM SQLAlchemy pour les abonnements tenant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.database import Base


@dataclass
class SaaSPlan:
    code: str
    name: str
    price_monthly: float = 0.0
    features: list[str] = field(default_factory=list)
    is_public: bool = True


@dataclass
class SaaSSubscription:
    store_id: int
    plan_code: str
    status: str = "active"
    expires_at: str | None = None


@dataclass
class CreditTopUpPack:
    pack_id: str
    credits: int
    price: float
    currency: str = "TND"


@dataclass
class TenantUsage:
    store_id: int
    credits_used: int = 0
    credits_remaining: int = 0
    plan_code: str = "free"


class CreditTopUpPackModel(Base):
    __tablename__ = "credit_top_up_packs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pack_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    credits_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    price_dt: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    price_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    bonus_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PlanLimits(Base):
    """Miroir ORM de la table `plan_limits` (migration 0027 + 0060).

    P1.5-FIX : la version précédente de cette classe (ajoutée pour permettre
    à Base.metadata.create_all() de créer cette table sous SQLite en test)
    déclarait price_3months_dt/price_6months_dt/price_12months_dt comme si
    elles existaient déjà en Postgres — elles n'existaient pas (migration
    0027 ne créait que price_monthly_dt/price_annual_dt). La migration 0060
    les ajoute désormais réellement ; cette classe est complétée pour rester
    un miroir fidèle de la table réelle (feature flags de la migration 0027
    qui manquaient aussi : crm_enabled, marketing_enabled, etc.) — une classe
    ORM qui ne reflète pas fidèlement la table réelle est un piège pour tout
    futur code qui l'utiliserait pour une vraie requête (aujourd'hui aucun
    code ne le fait — seul le SQL brut dans services/saas_billing.py touche
    cette table — mais ça ne doit pas rester une excuse pour un modèle faux).
    """
    __tablename__ = "plan_limits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    price_monthly_dt: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    price_monthly_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    price_3months_dt: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    price_6months_dt: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    price_12months_dt: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    price_annual_dt: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    price_annual_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    max_products: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    max_users: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    monthly_ai_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=500, server_default="500")
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    crm_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    crm_advanced_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    marketing_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    omnichannel_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    auto_followup_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    advanced_stats_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    priority_support_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    included_channels: Mapped[Any] = mapped_column(sa.JSON(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class TenantSubscription(Base):
    __tablename__ = "tenant_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    plan_code: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_months: Mapped[int] = mapped_column(Integer, nullable=False)
    price_paid_dt: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    price_paid_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_7d_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_1d_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class CreditLedger(Base):
    """
    P0-FIX (audit): CreditLedger model was missing, causing 500 in admin stats.
    Maps to 'credit_events' table created by migration 0033.
    """
    __tablename__ = "credit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True) # allocate, deduct, topup, expire, reset, refund
    credits_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    reference_id: Mapped[str | None] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    # P0-FIX: These fields were expected by credits_admin.py but missing from DB schema.
    # We add them as aliases or properties if possible, or just fix the query in credits_admin.py.
    # Looking at credits_admin.py:
    # CreditLedger.plan_code
    # CreditLedger.entry_type == "consumption"
    
    # We'll fix credits_admin.py to join with Store to get plan_code and use event_type.
