"""Merge remaining Alembic heads and add per-store currency.

Revision ID: 0066_merge_heads_add_store_currency
Revises: 0064_merge_rls_audit_and_loyalty, 0065_add_order_channel
Create Date: 2026-08-13
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0066_merge_heads_add_store_currency"
down_revision: Union[str, Sequence[str], None] = (
    "0064_merge_rls_audit_and_loyalty",
    "0065_add_order_channel",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stores",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="TND"),
    )
    op.execute(
        "UPDATE stores SET currency = CASE UPPER(COALESCE(country, 'TN')) "
        "WHEN 'TN' THEN 'TND' WHEN 'MA' THEN 'MAD' WHEN 'DZ' THEN 'DZD' "
        "WHEN 'AE' THEN 'AED' WHEN 'SA' THEN 'SAR' WHEN 'GB' THEN 'GBP' "
        "WHEN 'US' THEN 'USD' WHEN 'CA' THEN 'CAD' ELSE 'EUR' END"
    )
    op.alter_column("stores", "currency", server_default=None)


def downgrade() -> None:
    op.drop_column("stores", "currency")
