"""0020_drift_fix_stores_and_payment_links — PRODUCTION SAFE drift fix

Revision ID: 0020_drift_fix
Revises: 0019
Create Date: 2026-04-29

Reconcilie ORM (models/database.py) <-> migrations Alembic.

Corrections critiques :
  1. stores.is_paid                  — present dans ORM, manquant en migration
  2. stores.subscription_type        — present dans ORM, manquant en migration (legacy)
  3. stores.subscription_expires_at  — present dans ORM, manquant en migration (legacy)
  4. payment_links.url               — relacher NOT NULL -> NULL pour supporter Cash/COD
                                       (CashAdapter retourne url=None par design)

Aucune donnee existante n'est touchee. Les colonnes ajoutees sont nullable
ou ont un server_default (pas de re-ecriture de table).

Toutes les operations sont idempotentes : si la colonne existe deja
(par ex. ajoutee a la main en prod), l'operation est skip.
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# Revision identifiers
revision = "0020_drift_fix"
down_revision = "0019"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """Idempotency helper — check if a column already exists."""
    bind = op.get_bind()
    insp = inspect(bind)
    try:
        cols = [c["name"] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols


def _column_is_nullable(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    try:
        for c in insp.get_columns(table):
            if c["name"] == column:
                return bool(c.get("nullable", True))
    except Exception:
        pass
    return True


def upgrade() -> None:
    # ── 1) stores.is_paid (legacy billing flag) ──────────────────────────────
    if not _has_column("stores", "is_paid"):
        op.add_column(
            "stores",
            sa.Column(
                "is_paid",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    # ── 2) stores.subscription_type (legacy field, kept for backward compat) ─
    if not _has_column("stores", "subscription_type"):
        op.add_column(
            "stores",
            sa.Column("subscription_type", sa.String(length=20), nullable=True),
        )

    # ── 3) stores.subscription_expires_at (legacy field) ─────────────────────
    if not _has_column("stores", "subscription_expires_at"):
        op.add_column(
            "stores",
            sa.Column(
                "subscription_expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )

    # ── 4) payment_links.url : NOT NULL -> NULLABLE ───────────────────────────
    # Required to support Cash-on-Delivery (CashAdapter returns url=None).
    # Other providers still MUST provide a URL — enforced at API layer.
    if _has_column("payment_links", "url") and not _column_is_nullable("payment_links", "url"):
        op.alter_column(
            "payment_links",
            "url",
            existing_type=sa.String(length=1000),
            nullable=True,
        )


def downgrade() -> None:
    # Revert payment_links.url back to NOT NULL (will fail if rows have NULL).
    # Operators must clean up Cash payment links before downgrading.
    if _has_column("payment_links", "url") and _column_is_nullable("payment_links", "url"):
        op.alter_column(
            "payment_links",
            "url",
            existing_type=sa.String(length=1000),
            nullable=False,
        )

    if _has_column("stores", "subscription_expires_at"):
        op.drop_column("stores", "subscription_expires_at")
    if _has_column("stores", "subscription_type"):
        op.drop_column("stores", "subscription_type")
    if _has_column("stores", "is_paid"):
        op.drop_column("stores", "is_paid")
