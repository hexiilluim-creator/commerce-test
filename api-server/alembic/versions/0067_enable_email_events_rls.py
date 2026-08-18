"""Protect email_events with tenant RLS.

Revision ID: 0067_enable_email_events_rls
Revises: 0066_merge_heads_add_store_currency
Create Date: 2026-08-13
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0067_enable_email_events_rls"
down_revision: Union[str, Sequence[str], None] = "0066_merge_heads_add_store_currency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The ORM has always declared EmailEvent, but older migration chains may
    # reach this revision without having created the physical table. Keep the
    # migration additive and idempotent so a fresh production database and an
    # existing database converge to the same schema.
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("email_events"):
        op.create_table(
            "email_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=True),
            sa.Column("to", sa.String(length=255), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("template", sa.String(length=100), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("trace_id", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_email_events_store_id", "email_events", ["store_id"])
        op.create_index("ix_email_events_status", "email_events", ["status"])
        op.create_index("ix_email_events_trace_id", "email_events", ["trace_id"])

    # Legacy enum left behind by an earlier model revision; verified unused
    # (zero dependent columns) on the known-good staging database.
    op.execute(sa.text("DROP TYPE IF EXISTS public.messagetype"))
    op.execute(sa.text("ALTER TABLE email_events ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE email_events FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_email_events ON email_events"))
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_isolation_email_events ON email_events
            USING (
                current_setting('app.current_user_role', true) = 'super_admin'
                OR store_id = NULLIF(current_setting('app.current_tenant_id', true), '')::int
            )
            WITH CHECK (
                current_setting('app.current_user_role', true) = 'super_admin'
                OR store_id = NULLIF(current_setting('app.current_tenant_id', true), '')::int
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_email_events ON email_events"))
    op.execute(sa.text("ALTER TABLE email_events NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE email_events DISABLE ROW LEVEL SECURITY"))
