"""0039 — Float to Numeric(12,4) for all monetary columns

Revision ID: 0039_numeric_monetary
Revises: 0038_final_merge_head
Create Date: 2026-06-27 00:00:00

RAISON (P0 — Audit CTO):
  IEEE 754 Float produit des erreurs d'arrondi sur chaque transaction.
  Ex: 0.1 + 0.2 = 0.30000000000000004 en Float.
  Numeric(12,4) = précision exacte, jusqu'à 99,999,999.9999 DT par champ.
  Standard de l'industrie pour toutes les données financières.

TABLES/COLONNES MODIFIÉES:
  products.price              Float → Numeric(12,4)
  orders.total_amount         Float → Numeric(12,4)
  payment_links.amount        Float → Numeric(12,4)
  tenant_subscriptions.price_paid_dt/usd  Float → Numeric(12,4)

FIX (staging validation — Manus, 2026-06-30):
  La version précédente tentait ALTER COLUMN sur credit_events.amount et
  credit_ledger.amount — ces colonnes n'existent pas. La table credit_events
  (migration 0033) stocke des CRÉDITS IA en INTEGER (credits_delta,
  balance_after), pas des montants monétaires en Float — donc rien à
  convertir ici, ce n'est pas un oubli. La table credit_ledger n'est même
  pas créée par une migration (générée dynamiquement ou non utilisée en
  l'état) — la cibler n'avait pas de sens.
  Le try/except Exception: pass ne catchait pas l'erreur car
  asyncpg invalide la transaction PostgreSQL entière dès la première
  commande SQL en échec (UndefinedColumnError) ; toute commande suivante
  dans le même bloc Alembic hérite de cette transaction avortée. Retiré.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0039_numeric_monetary"
down_revision = "0038_final_merge_head"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    try:
        cols = [c["name"] for c in inspect(bind).get_columns(table)]
        return column in cols
    except Exception:
        return False


def upgrade() -> None:
    # products.price
    op.alter_column("products", "price",
        existing_type=sa.Float(),
        type_=sa.Numeric(12, 4),
        existing_nullable=False,
        postgresql_using="price::numeric(12,4)"
    )

    # orders.total_amount
    op.alter_column("orders", "total_amount",
        existing_type=sa.Float(),
        type_=sa.Numeric(12, 4),
        existing_nullable=False,
        postgresql_using="total_amount::numeric(12,4)"
    )

    # payment_links.amount (nullable)
    if _has_column("payment_links", "amount"):
        op.alter_column("payment_links", "amount",
            existing_type=sa.Float(),
            type_=sa.Numeric(12, 4),
            existing_nullable=True,
            postgresql_using="amount::numeric(12,4)"
        )

    # tenant_subscriptions.price_paid_dt / price_paid_usd
    for col in ("price_paid_dt", "price_paid_usd"):
        if _has_column("tenant_subscriptions", col):
            op.alter_column("tenant_subscriptions", col,
                existing_type=sa.Float(),
                type_=sa.Numeric(12, 4),
                existing_nullable=True,
                postgresql_using=f"{col}::numeric(12,4)"
            )

    # credit_events / credit_ledger: NO monetary 'amount' column to convert.
    # credit_events.credits_delta and balance_after are Integer (credit
    # units, not currency) — left untouched intentionally.


def downgrade() -> None:
    # Revert to Float (precision lost — not recommended in production)
    op.alter_column("products", "price",
        existing_type=sa.Numeric(12, 4),
        type_=sa.Float(),
        existing_nullable=False,
    )
    op.alter_column("orders", "total_amount",
        existing_type=sa.Numeric(12, 4),
        type_=sa.Float(),
        existing_nullable=False,
    )
    if _has_column("payment_links", "amount"):
        op.alter_column("payment_links", "amount",
            existing_type=sa.Numeric(12, 4),
            type_=sa.Float(),
            existing_nullable=True,
        )
