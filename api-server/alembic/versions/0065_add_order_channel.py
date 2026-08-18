"""Add order channel provenance.

Revision ID: 0065_add_order_channel
Revises: b09e4521bd0c
Create Date: 2026-08-11

The storefront and order dashboard need a persisted source channel. Previously
orders had no channel column, so the UI could not display whether an order came
from the public storefront or a social channel.
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0065_add_order_channel"
down_revision: Union[str, None] = "b09e4521bd0c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("channel", sa.String(length=32), nullable=True, server_default="direct"),
    )
    op.execute("UPDATE orders SET channel = 'direct' WHERE channel IS NULL")
    op.alter_column("orders", "channel", nullable=False, server_default="direct")
    op.create_index("ix_orders_channel", "orders", ["channel"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_orders_channel", table_name="orders")
    op.drop_column("orders", "channel")
