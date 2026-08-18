"""0040 — Add RETURNED and REFUNDED to orderstatus enum

Revision ID: 0040_order_status_returned_refunded
Revises: 0039_numeric_monetary
Create Date: 2026-06-27 00:00:00

RAISON (P1 — Audit CTO):
  Le cycle de vie complet d'une commande nécessite RETURNED et REFUNDED.
  Sans ces états, les marchands ne peuvent pas tracker les retours et
  remboursements dans la plateforme. CANCELLED était le seul état terminal.

FIX (staging validation réelle — 2026-07-02):
  Bug confirmé en déploiement réel : "type orderstatus does not exist".
  Cause racine : 0001_initial.py crée orders.status comme VARCHAR(20)
  simple (server_default="pending"), JAMAIS comme type PostgreSQL ENUM
  nommé "orderstatus". Le modèle SQLAlchemy (models/database.py) déclare
  bien `SAEnum(OrderStatus, ...)`, ce qui pousse SQLAlchemy à créer ce
  type automatiquement UNIQUEMENT quand Base.metadata.create_all() gère
  la création du schéma — jamais quand le schéma est créé par les
  migrations Alembic elles-mêmes. Résultat : sur toute base migrée avec
  `alembic upgrade head` depuis zéro (le cas réel de production), le
  type orderstatus n'a jamais existé avant cette migration.
  Cette version crée le type explicitement s'il est absent, migre les
  valeurs existantes, PUIS convertit la colonne VARCHAR vers le type ENUM.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0040_order_status_returned_refunded"
down_revision = "0039_numeric_monetary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    with op.get_context().autocommit_block():
        # 1. Crée le type orderstatus s'il n'existe pas encore (cas réel:
        #    base migrée intégralement via Alembic, jamais via create_all()).
        op.execute(sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'orderstatus') THEN
                    CREATE TYPE orderstatus AS ENUM (
                        'pending', 'confirmed', 'paid', 'shipped',
                        'delivered', 'cancelled', 'returned', 'refunded'
                    );
                END IF;
            END
            $$;
            """
        ))
        # 2. Ajoute les valeurs manquantes si le type existait déjà
        #    (cas: base créée via Base.metadata.create_all() en dev/test,
        #    où le type existe mais sans returned/refunded).
        op.execute(sa.text("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'returned'"))
        op.execute(sa.text("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'refunded'"))

    # 3. Convertit orders.status de VARCHAR vers le type orderstatus,
    #    si ce n'est pas déjà fait (idempotent — vérifie le type réel de
    #    la colonne avant de tenter la conversion).
    inspector = sa.inspect(bind)
    columns = {c["name"]: c for c in inspector.get_columns("orders")}
    current_type = str(columns.get("status", {}).get("type", "")).lower()

    if "orderstatus" not in current_type:
        # Suppression du default existant (VARCHAR) pour éviter le blocage du cast
        op.execute(sa.text("ALTER TABLE orders ALTER COLUMN status DROP DEFAULT"))
        
        op.execute(sa.text(
            """
            ALTER TABLE orders
            ALTER COLUMN status TYPE orderstatus
            USING status::text::orderstatus
            """
        ))
        op.alter_column(
            "orders", "status",
            server_default=sa.text("'pending'::orderstatus"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # Revert orders.status to plain VARCHAR(20) — matches 0001_initial state.
    op.execute(sa.text(
        """
        ALTER TABLE orders
        ALTER COLUMN status TYPE VARCHAR(20)
        USING status::text
        """
    ))
    op.alter_column("orders", "status", server_default=sa.text("'pending'"))
    # PostgreSQL does not support removing enum values or the type itself
    # while it may still be referenced — the orderstatus type is left in place.
