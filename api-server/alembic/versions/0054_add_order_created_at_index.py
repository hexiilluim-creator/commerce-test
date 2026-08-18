"""0054_add_order_created_at_index — Index sur orders.created_at.

Revision ID: 0054_add_order_created_at_index
Revises: 0053_add_store_social_mappings
Create Date: 2026-07-13

Contexte :
  Le tri/filtre des commandes par date (dashboard, exports, rapports
  périodiques) est une requête fréquente en usage SaaS multi-tenant.
  `index=True` a été ajouté sur `Order.created_at` dans models/database.py ;
  cette migration crée réellement l'index correspondant en base. (Ajouter
  `index=True` au modèle ORM seul ne suffit pas sur une base déjà
  déployée — c'est exactement le type de drift schéma/code identifié et
  corrigé ailleurs dans cet audit pour blueprints/store_social_mappings.)
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0054_add_order_created_at_index"
down_revision = "0053_add_store_social_mappings"
branch_labels = None
depends_on = None


def _index_exists(bind: sa.Connection, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(ix["name"] == index_name for ix in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _index_exists(bind, "orders", "ix_orders_created_at"):
        op.create_index("ix_orders_created_at", "orders", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if _index_exists(bind, "orders", "ix_orders_created_at"):
        op.drop_index("ix_orders_created_at", table_name="orders")
