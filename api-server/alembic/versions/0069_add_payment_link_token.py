"""Add opaque token for AI-generated payment links.

Revision ID: 0069_add_payment_link_token
Revises: 0068_normalize_email_events_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0069_add_payment_link_token"
down_revision = "0068_normalize_email_events_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payment_links", sa.Column("token", sa.String(length=64), nullable=True))
    op.create_index("ix_payment_links_token", "payment_links", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_payment_links_token", table_name="payment_links")
    op.drop_column("payment_links", "token")
