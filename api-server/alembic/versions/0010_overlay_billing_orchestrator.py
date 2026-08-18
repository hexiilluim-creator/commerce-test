"""overlay billing and ai usage ledger

Revision ID: 0010_overlay_billing_orchestrator
Revises: 0009_omnichannel_customer
Create Date: 2026-04-25 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "0010_billing_orch"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_billing_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("plan_code", sa.String(length=32), nullable=False, server_default="free"),
        sa.Column("plan_status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("billing_email", sa.String(length=255), nullable=True),
        sa.Column("feature_overrides", sa.JSON(), nullable=True),
        sa.Column("quota_overrides", sa.JSON(), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("store_id"),
    )
    op.create_index("ix_tenant_billing_profiles_store_id", "tenant_billing_profiles", ["store_id"], unique=True)
    op.create_index("ix_tenant_billing_profiles_plan_code", "tenant_billing_profiles", ["plan_code"], unique=False)
    op.create_index("ix_tenant_billing_profiles_plan_status", "tenant_billing_profiles", ["plan_status"], unique=False)
    op.create_index("ix_tenant_billing_profiles_current_period_end", "tenant_billing_profiles", ["current_period_end"], unique=False)

    op.create_table(
        "tenant_ai_usage_ledger",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("plan_code", sa.String(length=32), nullable=False, server_default="free"),
        sa.Column("is_paid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("feature_key", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("blocked_reason", sa.String(length=128), nullable=True),
        sa.Column("request_path", sa.String(length=255), nullable=True),
        sa.Column("request_method", sa.String(length=16), nullable=True),
        sa.Column("queue_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("execution_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenant_ai_usage_ledger_request_id", "tenant_ai_usage_ledger", ["request_id"], unique=False)
    op.create_index("ix_tenant_ai_usage_ledger_trace_id", "tenant_ai_usage_ledger", ["trace_id"], unique=False)
    op.create_index("ix_tenant_ai_usage_ledger_store_id", "tenant_ai_usage_ledger", ["store_id"], unique=False)
    op.create_index("ix_tenant_ai_usage_ledger_plan_code", "tenant_ai_usage_ledger", ["plan_code"], unique=False)
    op.create_index("ix_tenant_ai_usage_ledger_status", "tenant_ai_usage_ledger", ["status"], unique=False)
    op.create_index("ix_tenant_ai_usage_ledger_kind", "tenant_ai_usage_ledger", ["kind"], unique=False)
    op.create_index("ix_tenant_ai_usage_ledger_feature_key", "tenant_ai_usage_ledger", ["feature_key"], unique=False)
    op.create_index("ix_tenant_ai_usage_ledger_blocked_reason", "tenant_ai_usage_ledger", ["blocked_reason"], unique=False)
    op.create_index("ix_tenant_ai_usage_ledger_created_at", "tenant_ai_usage_ledger", ["created_at"], unique=False)
    op.create_index("ix_tenant_ai_usage_ledger_completed_at", "tenant_ai_usage_ledger", ["completed_at"], unique=False)
    op.create_index(
        "ix_tenant_ai_usage_store_status_created",
        "tenant_ai_usage_ledger",
        ["store_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_tenant_ai_usage_store_kind_created",
        "tenant_ai_usage_ledger",
        ["store_id", "kind", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_ai_usage_store_kind_created", table_name="tenant_ai_usage_ledger")
    op.drop_index("ix_tenant_ai_usage_store_status_created", table_name="tenant_ai_usage_ledger")
    op.drop_index("ix_tenant_ai_usage_ledger_completed_at", table_name="tenant_ai_usage_ledger")
    op.drop_index("ix_tenant_ai_usage_ledger_created_at", table_name="tenant_ai_usage_ledger")
    op.drop_index("ix_tenant_ai_usage_ledger_blocked_reason", table_name="tenant_ai_usage_ledger")
    op.drop_index("ix_tenant_ai_usage_ledger_feature_key", table_name="tenant_ai_usage_ledger")
    op.drop_index("ix_tenant_ai_usage_ledger_kind", table_name="tenant_ai_usage_ledger")
    op.drop_index("ix_tenant_ai_usage_ledger_status", table_name="tenant_ai_usage_ledger")
    op.drop_index("ix_tenant_ai_usage_ledger_plan_code", table_name="tenant_ai_usage_ledger")
    op.drop_index("ix_tenant_ai_usage_ledger_store_id", table_name="tenant_ai_usage_ledger")
    op.drop_index("ix_tenant_ai_usage_ledger_trace_id", table_name="tenant_ai_usage_ledger")
    op.drop_index("ix_tenant_ai_usage_ledger_request_id", table_name="tenant_ai_usage_ledger")
    op.drop_table("tenant_ai_usage_ledger")

    op.drop_index("ix_tenant_billing_profiles_current_period_end", table_name="tenant_billing_profiles")
    op.drop_index("ix_tenant_billing_profiles_plan_status", table_name="tenant_billing_profiles")
    op.drop_index("ix_tenant_billing_profiles_plan_code", table_name="tenant_billing_profiles")
    op.drop_index("ix_tenant_billing_profiles_store_id", table_name="tenant_billing_profiles")
    op.drop_table("tenant_billing_profiles")
