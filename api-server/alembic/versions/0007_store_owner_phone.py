"""0007_store_owner_phone — Ajoute owner_phone sur la table stores

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-23
"""
import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stores",
        sa.Column("owner_phone", sa.String(20), nullable=True),
    )
    op.create_index("ix_stores_owner_phone", "stores", ["owner_phone"])


def downgrade() -> None:
    op.drop_index("ix_stores_owner_phone", table_name="stores")
    op.drop_column("stores", "owner_phone")
