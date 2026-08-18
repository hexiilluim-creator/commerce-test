"""0053_add_store_social_mappings — Crée la table store_social_mappings.

Revision ID: 0053_add_store_social_mappings
Revises: 0052_add_blueprints_tables
Create Date: 2026-07-12

Contexte (audit) :
  services/store_resolver.py référence models.database.StoreSocialMapping
  depuis sa création (docstring : "3. DB PostgreSQL via StoreSocialMapping
  — vérité absolue") pour résoudre store_id depuis un compte Instagram/
  Facebook/TikTok/Messenger. Le modèle n'existait pas du tout (ni classe
  ORM, ni migration) : la résolution DB pour ces canaux était donc
  totalement non fonctionnelle (ImportError), masquée jusqu'ici par un bug
  de mock qui empêchait ce chemin de code de s'exécuter en test.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0053_add_store_social_mappings"
down_revision = "0052_add_blueprints_tables"
branch_labels = None
depends_on = None


def _table_exists(bind: sa.Connection, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "store_social_mappings"):
        return

    op.create_table(
        "store_social_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"],
            name="fk_store_social_mappings_store_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("channel", "account_id", name="uq_store_social_mappings_channel_account"),
    )
    op.create_index(
        "ix_store_social_mappings_channel", "store_social_mappings", ["channel"]
    )
    op.create_index(
        "ix_store_social_mappings_account_id", "store_social_mappings", ["account_id"]
    )
    op.create_index(
        "ix_store_social_mappings_store_id", "store_social_mappings", ["store_id"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "store_social_mappings"):
        op.drop_table("store_social_mappings")
