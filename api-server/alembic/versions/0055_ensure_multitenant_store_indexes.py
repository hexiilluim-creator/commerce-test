"""0055_ensure_multitenant_store_indexes — garantit les index store_id multi-tenant.

Revision ID: 0055_ensure_multitenant_store_indexes
Revises: 0054_add_order_created_at_index
Create Date: 2026-07-15

Contexte :
  Le guide de finalisation Bloc 3 demande de garantir un index sur `store_id`
  pour les tables principales utilisées en isolation multi-tenant.
  Certaines bases peuvent avoir subi un drift (restauration partielle, ancienne
  branche Alembic, import SQL incomplet). Cette migration est idempotente et
  recrée les index manquants sans casser les environnements déjà à jour.

Tables couvertes :
  - orders.store_id
  - products.store_id
  - conversation_logs.store_id
  - conversations.store_id (si cette table existe dans un déploiement legacy)
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0055_ensure_multitenant_store_indexes"
down_revision = "0054_add_order_created_at_index"
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _index_exists(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(ix["name"] == index_name for ix in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    indexes_to_ensure = (
        ("orders", "ix_orders_store_id", ["store_id"]),
        ("products", "ix_products_store_id", ["store_id"]),
        ("conversation_logs", "ix_conversation_logs_store_id", ["store_id"]),
        ("conversations", "ix_conversations_store_id", ["store_id"]),
    )

    for table_name, index_name, columns in indexes_to_ensure:
        if _table_exists(inspector, table_name) and not _index_exists(inspector, table_name, index_name):
            op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    indexes_to_drop = (
        ("orders", "ix_orders_store_id"),
        ("products", "ix_products_store_id"),
        ("conversation_logs", "ix_conversation_logs_store_id"),
        ("conversations", "ix_conversations_store_id"),
    )

    for table_name, index_name in indexes_to_drop:
        if _table_exists(inspector, table_name) and _index_exists(inspector, table_name, index_name):
            op.drop_index(index_name, table_name=table_name)
