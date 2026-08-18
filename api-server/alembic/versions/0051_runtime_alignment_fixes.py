"""0051_runtime_alignment_fixes — orderstatus enum + credit pack normalization.

Revision ID: 0051_runtime_alignment_fixes
Revises: 0050_merge_fg_plans_into_main
Create Date: 2026-07-01

Objectifs:
  1. Corriger définitivement les environnements où 0040 est déjà passé avec un
     upgrade() vide en ajoutant les valeurs returned / refunded à orderstatus.
  2. Normaliser le catalogue credit_top_up_packs pour l'aligner sur les codes
     réellement consommés par le backend et le frontend.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0051_runtime_alignment_fixes"
down_revision = "0050_merge_fg_plans_into_main"
branch_labels = None
depends_on = None


def _table_exists(bind: sa.Connection, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _index_exists(bind: sa.Connection, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def _ensure_credit_top_up_packs_table(bind: sa.Connection) -> None:
    if _table_exists(bind, "credit_top_up_packs"):
        return

    op.create_table(
        "credit_top_up_packs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pack_code", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("credits_amount", sa.Integer(), nullable=False),
        sa.Column("price_dt", sa.Float(), nullable=False, server_default="0"),
        sa.Column("price_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("bonus_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_credit_top_up_packs_pack_code", "credit_top_up_packs", ["pack_code"], unique=True)
    op.create_index("ix_credit_top_up_packs_is_active", "credit_top_up_packs", ["is_active"], unique=False)


def _normalize_credit_top_up_packs(bind: sa.Connection) -> None:
    _ensure_credit_top_up_packs_table(bind)

    if not _index_exists(bind, "credit_top_up_packs", "ix_credit_top_up_packs_pack_code"):
        op.create_index("ix_credit_top_up_packs_pack_code", "credit_top_up_packs", ["pack_code"], unique=True)
    if not _index_exists(bind, "credit_top_up_packs", "credit_top_up_packs_is_active") and not _index_exists(bind, "credit_top_up_packs", "ix_credit_top_up_packs_is_active"):
        op.create_index("ix_credit_top_up_packs_is_active", "credit_top_up_packs", ["is_active"], unique=False)

    op.execute(
        sa.text(
            """
            DELETE FROM credit_top_up_packs
            WHERE pack_code IN ('top_up_1k', 'top_up_5k', 'top_up_10k')
            """
        )
    )

    canonical_rows = [
        {
            "pack_code": "starter_50",
            "display_name": "50 crédits IA",
            "credits_amount": 50,
            "price_dt": 25.00,
            "price_usd": 8.25,
            "bonus_credits": 0,
            "is_active": True,
            "rank": 10,
        },
        {
            "pack_code": "growth_200",
            "display_name": "200 crédits IA",
            "credits_amount": 200,
            "price_dt": 80.00,
            "price_usd": 26.40,
            "bonus_credits": 0,
            "is_active": True,
            "rank": 20,
        },
        {
            "pack_code": "business_500",
            "display_name": "500 crédits IA",
            "credits_amount": 500,
            "price_dt": 175.00,
            "price_usd": 57.75,
            "bonus_credits": 0,
            "is_active": True,
            "rank": 30,
        },
        {
            "pack_code": "enterprise_1k",
            "display_name": "1000 crédits IA",
            "credits_amount": 1000,
            "price_dt": 300.00,
            "price_usd": 99.00,
            "bonus_credits": 0,
            "is_active": True,
            "rank": 40,
        },
    ]

    for row in canonical_rows:
        bind.execute(
            sa.text(
                """
                INSERT INTO credit_top_up_packs (
                    pack_code, display_name, credits_amount,
                    price_dt, price_usd, bonus_credits, is_active, rank
                ) VALUES (
                    :pack_code, :display_name, :credits_amount,
                    :price_dt, :price_usd, :bonus_credits, :is_active, :rank
                )
                ON CONFLICT (pack_code) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    credits_amount = EXCLUDED.credits_amount,
                    price_dt = EXCLUDED.price_dt,
                    price_usd = EXCLUDED.price_usd,
                    bonus_credits = EXCLUDED.bonus_credits,
                    is_active = EXCLUDED.is_active,
                    rank = EXCLUDED.rank
                """
            ),
            row,
        )


def _ensure_orderstatus_enum(bind: sa.Connection) -> None:
    if bind.dialect.name != "postgresql":
        return

    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_type WHERE typname = 'orderstatus'
                    ) THEN
                        CREATE TYPE orderstatus AS ENUM (
                            'pending', 'confirmed', 'paid', 'shipped',
                            'delivered', 'cancelled', 'returned', 'refunded'
                        );
                    END IF;
                END
                $$;
                """
            )
        )
        op.execute(sa.text("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'returned'"))
        op.execute(sa.text("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'refunded'"))


def upgrade() -> None:
    bind = op.get_bind()
    _ensure_orderstatus_enum(bind)
    _normalize_credit_top_up_packs(bind)


def downgrade() -> None:
    # Downgrade best-effort: we keep the enum values (PostgreSQL cannot drop them safely).
    op.execute(
        sa.text(
            """
            DELETE FROM credit_top_up_packs
            WHERE pack_code IN ('starter_50', 'growth_200', 'business_500', 'enterprise_1k')
            """
        )
    )
