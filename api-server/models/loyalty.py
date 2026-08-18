"""
models/loyalty.py — Plan C1 Loyalty: Points, History, Earn, Spend, Balance.

Modèles manquants reconstruits à partir de l'usage réel dans
`services/loyalty_service.py` (Plan C1 — le fichier existait et importait
ces classes depuis `models.loyalty`, mais ce module n'avait jamais été créé :
`services.loyalty_service` échouait donc systématiquement à l'import).

Découvert lors d'un audit de déploiement (Manus, juillet 2026). À ce jour,
`services/loyalty_service.py` n'est appelé par aucune route/router — cette
reconstruction rend le module chargeable et fonctionnel, mais il reste à
brancher explicitement sur des endpoints si la feature "points de fidélité"
(distincte de Plan E3 "Loyalty IA" dans `models/loyalty_ia.py`, qui concerne
la segmentation et les recommandations, pas le portefeuille de points) doit
être exposée aux clients.

Tables :
  - loyalty_programs        : configuration du programme par store (1:1 store)
  - loyalty_rules           : règles de gain de points (points par euro)
  - loyalty_accounts        : portefeuille de points par (store, customer)
  - loyalty_ledger_entries  : historique immuable des mouvements (earn/spend)
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base


class LoyaltyProgram(Base):
    __tablename__ = "loyalty_programs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), default="Programme fidélité")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    default_points_per_eur: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("store_id", name="uq_loyalty_program_store"),
    )


class LoyaltyRule(Base):
    __tablename__ = "loyalty_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), default="Règle par défaut")
    points_per_eur: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LoyaltyAccount(Base):
    __tablename__ = "loyalty_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("store_id", "customer_id", name="uq_loyalty_account_store_customer"),
    )


class LoyaltyLedgerEntry(Base):
    __tablename__ = "loyalty_ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("loyalty_accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # "earn" | "spend"
    points: Mapped[int] = mapped_column(Integer, nullable=False)  # signé : +earn / -spend
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    amount_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("loyalty_rules.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_loyalty_ledger_idempotency_key"),
    )
