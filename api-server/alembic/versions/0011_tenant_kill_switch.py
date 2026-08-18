"""tenant kill switch overlay

Revision ID: 0011_tenant_kill_switch
Revises: 0010_overlay_billing_orchestrator
Create Date: 2026-04-25 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "0011_kill_switch"
down_revision = "0010_billing_orch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stores",
        sa.Column("billing_status", sa.String(length=20), nullable=False, server_default="active"),
    )
    op.add_column(
        "stores",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "stores",
        sa.Column("suspended_reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_stores_billing_status", "stores", ["billing_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_stores_billing_status", table_name="stores")
    op.drop_column("stores", "suspended_reason")
    op.drop_column("stores", "suspended_at")
    op.drop_column("stores", "billing_status")
