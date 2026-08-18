"""0032 — add opted_out fields to customers

Revision ID: 0032_customer_opted_out
Revises: 0031_whatsapp_message_manual_reply
Create Date: 2026-06-15 00:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = "0032_customer_opted_out"
down_revision = "0031_whatsapp_message_manual_reply"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("opted_out", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "customers",
        sa.Column("opted_out_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_customers_opted_out", "customers", ["store_id", "opted_out"])


def downgrade() -> None:
    op.drop_index("ix_customers_opted_out", table_name="customers")
    op.drop_column("customers", "opted_out_at")
    op.drop_column("customers", "opted_out")
