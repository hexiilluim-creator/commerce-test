"""0019_expenses_and_dlq — Spending Tracker + Dead Letter Queue
Revision ID: 0019
Revises: 0018_pay_links
Create Date: 2026-04-26
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0019"
down_revision = "0018_pay_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Expenses (Spending Tracker) ─────────────────────────────────────────
    op.execute("""DO $$ BEGIN
        CREATE TYPE expensecategory AS ENUM
            ('supplier','fixed','marketing','staff','logistics','other');
        EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;""")

    op.create_table("expenses",
        sa.Column("id",           sa.Integer(),  primary_key=True),
        sa.Column("store_id",     sa.Integer(),  sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description",  sa.String(500), nullable=False),
        sa.Column("vendor",       sa.String(255), nullable=True),
        sa.Column("amount",       sa.Float(),    nullable=False),
        sa.Column("currency",     sa.String(5),  server_default="TND"),
        sa.Column("category",     postgresql.ENUM("supplier","fixed","marketing","staff","logistics","other",
                                          name="expensecategory", create_type=False), nullable=False, server_default="other"),
        sa.Column("note",         sa.Text(),     nullable=True),
        sa.Column("expense_date", sa.Date(),     nullable=False),
        sa.Column("scanned_from_invoice", sa.Boolean(), server_default="false"),
        sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_expenses_store_date", "expenses", ["store_id", "expense_date"])

    # ── Dead Letter Queue ────────────────────────────────────────────────────
    op.create_table("failed_tasks",
        sa.Column("id",          sa.Integer(),  primary_key=True),
        sa.Column("store_id",    sa.Integer(),  sa.ForeignKey("stores.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_name",   sa.String(200), nullable=False),
        sa.Column("payload",     sa.JSON(),     nullable=True),
        sa.Column("channel",     sa.String(20), nullable=True),
        sa.Column("error",       sa.Text(),     nullable=True),
        sa.Column("retry_count", sa.Integer(),  default=0),
        sa.Column("failed_at",   sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(100), nullable=True),
    )
    op.create_index("ix_failed_tasks_store",     "failed_tasks", ["store_id"])
    op.create_index("ix_failed_tasks_failed_at", "failed_tasks", ["failed_at"])


def downgrade() -> None:
    op.drop_index("ix_failed_tasks_failed_at", table_name="failed_tasks")
    op.drop_index("ix_failed_tasks_store",     table_name="failed_tasks")
    op.drop_table("failed_tasks")
    op.drop_index("ix_expenses_store_date", table_name="expenses")
    op.drop_table("expenses")
    op.execute("DROP TYPE IF EXISTS expensecategory")
