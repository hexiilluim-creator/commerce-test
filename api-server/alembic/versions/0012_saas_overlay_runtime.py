"""saas overlay runtime tables and indexes

Revision ID: 0012_saas_overlay_runtime
Revises: 0011_tenant_kill_switch
Create Date: 2026-04-25
"""

import sqlalchemy as sa

from alembic import op

revision = "0012_saas_runtime"
down_revision = "0011_kill_switch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("billing_plan_code", sa.String(length=32), nullable=True))
    op.create_index("ix_stores_billing_plan_code", "stores", ["billing_plan_code"], unique=False)

    op.create_unique_constraint(
        "uq_customers_store_channel_sender",
        "customers",
        ["store_id", "channel", "social_sender_id"],
    )

    op.create_table(
        "saas_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_code", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price_monthly_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ai_budget_hard_limit_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ai_max_monthly_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_max_monthly_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("features_json", sa.JSON(), nullable=True),
        sa.Column("quotas_json", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_saas_plans_plan_code", "saas_plans", ["plan_code"], unique=True)
    op.create_index("ix_saas_plans_is_active", "saas_plans", ["is_active"], unique=False)

    op.create_table(
        "saas_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("saas_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("billing_plan_code", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("external_customer_id", sa.String(length=128), nullable=True),
        sa.Column("external_subscription_id", sa.String(length=128), nullable=True),
        sa.Column("is_paid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("renewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checkout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("portal_url", sa.String(length=1000), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "billing_plan_code", "status", name="uq_saas_subscription_tenant_plan_status"),
    )
    op.create_index("ix_saas_subscriptions_tenant_id", "saas_subscriptions", ["tenant_id"], unique=False)
    op.create_index("ix_saas_subscriptions_plan_id", "saas_subscriptions", ["plan_id"], unique=False)
    op.create_index("ix_saas_subscriptions_billing_plan_code", "saas_subscriptions", ["billing_plan_code"], unique=False)
    op.create_index("ix_saas_subscriptions_status", "saas_subscriptions", ["status"], unique=False)
    op.create_index("ix_saas_subscriptions_is_paid", "saas_subscriptions", ["is_paid"], unique=False)
    op.create_index("ix_saas_subscriptions_current_period_end", "saas_subscriptions", ["current_period_end"], unique=False)
    op.create_index("ix_saas_subscriptions_tenant_status", "saas_subscriptions", ["tenant_id", "status"], unique=False)

    op.create_table(
        "monthly_usage_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("billing_period", sa.Date(), nullable=False),
        sa.Column("total_ai_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_ai_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_ai_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("by_agent_json", sa.JSON(), nullable=True),
        sa.Column("by_channel_json", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "billing_period", name="uq_monthly_usage_snapshots_tenant_period"),
    )
    op.create_index("ix_monthly_usage_snapshots_tenant_id", "monthly_usage_snapshots", ["tenant_id"], unique=False)
    op.create_index("ix_monthly_usage_snapshots_billing_period", "monthly_usage_snapshots", ["billing_period"], unique=False)

    op.create_table(
        "ai_usage_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("saas_subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("fallback_model_name", sa.String(length=128), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("degraded_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("warning_threshold_reached", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("response_strategy", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_usage_events_request_id", "ai_usage_events", ["request_id"], unique=False)
    op.create_index("ix_ai_usage_events_tenant_id", "ai_usage_events", ["tenant_id"], unique=False)
    op.create_index("ix_ai_usage_events_subscription_id", "ai_usage_events", ["subscription_id"], unique=False)
    op.create_index("ix_ai_usage_events_agent_name", "ai_usage_events", ["agent_name"], unique=False)
    op.create_index("ix_ai_usage_events_model_name", "ai_usage_events", ["model_name"], unique=False)
    op.create_index("ix_ai_usage_events_channel", "ai_usage_events", ["channel"], unique=False)
    op.create_index("ix_ai_usage_events_status", "ai_usage_events", ["status"], unique=False)
    op.create_index("ix_ai_usage_events_timestamp", "ai_usage_events", ["timestamp"], unique=False)
    op.create_index("ix_ai_usage_events_tenant_timestamp", "ai_usage_events", ["tenant_id", "timestamp"], unique=False)
    op.create_index("ix_ai_usage_events_tenant_agent_timestamp", "ai_usage_events", ["tenant_id", "agent_name", "timestamp"], unique=False)
    op.create_index("ix_ai_usage_events_tenant_channel_timestamp", "ai_usage_events", ["tenant_id", "channel", "timestamp"], unique=False)

    op.create_table(
        "workflow_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_key", sa.String(length=191), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="SET NULL"), nullable=True),
        sa.Column("workflow_type", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=True),
        sa.Column("external_event_id", sa.String(length=191), nullable=True),
        sa.Column("message_id", sa.String(length=191), nullable=True),
        sa.Column("signature_status", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("replay_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dlq_name", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("error_class", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workflow_events_event_key", "workflow_events", ["event_key"], unique=True)
    op.create_index("ix_workflow_events_tenant_id", "workflow_events", ["tenant_id"], unique=False)
    op.create_index("ix_workflow_events_workflow_type", "workflow_events", ["workflow_type"], unique=False)
    op.create_index("ix_workflow_events_provider", "workflow_events", ["provider"], unique=False)
    op.create_index("ix_workflow_events_channel", "workflow_events", ["channel"], unique=False)
    op.create_index("ix_workflow_events_external_event_id", "workflow_events", ["external_event_id"], unique=False)
    op.create_index("ix_workflow_events_message_id", "workflow_events", ["message_id"], unique=False)
    op.create_index("ix_workflow_events_signature_status", "workflow_events", ["signature_status"], unique=False)
    op.create_index("ix_workflow_events_status", "workflow_events", ["status"], unique=False)
    op.create_index("ix_workflow_events_received_at", "workflow_events", ["received_at"], unique=False)
    op.create_index("ix_workflow_events_type_status_received", "workflow_events", ["workflow_type", "status", "received_at"], unique=False)
    op.create_index("ix_workflow_events_tenant_status_received", "workflow_events", ["tenant_id", "status", "received_at"], unique=False)

    op.create_index("ix_orders_store_status_created_at", "orders", ["store_id", "status", "created_at"], unique=False)
    op.create_index("ix_orders_store_customer_created_at", "orders", ["store_id", "customer_id", "created_at"], unique=False)
    op.create_index("ix_whatsapp_messages_store_processed_created_at", "whatsapp_messages", ["store_id", "processed", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_whatsapp_messages_store_processed_created_at", table_name="whatsapp_messages")
    op.drop_index("ix_orders_store_customer_created_at", table_name="orders")
    op.drop_index("ix_orders_store_status_created_at", table_name="orders")

    op.drop_index("ix_workflow_events_tenant_status_received", table_name="workflow_events")
    op.drop_index("ix_workflow_events_type_status_received", table_name="workflow_events")
    op.drop_index("ix_workflow_events_received_at", table_name="workflow_events")
    op.drop_index("ix_workflow_events_status", table_name="workflow_events")
    op.drop_index("ix_workflow_events_signature_status", table_name="workflow_events")
    op.drop_index("ix_workflow_events_message_id", table_name="workflow_events")
    op.drop_index("ix_workflow_events_external_event_id", table_name="workflow_events")
    op.drop_index("ix_workflow_events_channel", table_name="workflow_events")
    op.drop_index("ix_workflow_events_provider", table_name="workflow_events")
    op.drop_index("ix_workflow_events_workflow_type", table_name="workflow_events")
    op.drop_index("ix_workflow_events_tenant_id", table_name="workflow_events")
    op.drop_index("ix_workflow_events_event_key", table_name="workflow_events")
    op.drop_table("workflow_events")

    op.drop_index("ix_ai_usage_events_tenant_channel_timestamp", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_tenant_agent_timestamp", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_tenant_timestamp", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_timestamp", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_status", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_channel", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_model_name", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_agent_name", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_subscription_id", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_tenant_id", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_request_id", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")

    op.drop_index("ix_monthly_usage_snapshots_billing_period", table_name="monthly_usage_snapshots")
    op.drop_index("ix_monthly_usage_snapshots_tenant_id", table_name="monthly_usage_snapshots")
    op.drop_table("monthly_usage_snapshots")

    op.drop_index("ix_saas_subscriptions_tenant_status", table_name="saas_subscriptions")
    op.drop_index("ix_saas_subscriptions_current_period_end", table_name="saas_subscriptions")
    op.drop_index("ix_saas_subscriptions_is_paid", table_name="saas_subscriptions")
    op.drop_index("ix_saas_subscriptions_status", table_name="saas_subscriptions")
    op.drop_index("ix_saas_subscriptions_billing_plan_code", table_name="saas_subscriptions")
    op.drop_index("ix_saas_subscriptions_plan_id", table_name="saas_subscriptions")
    op.drop_index("ix_saas_subscriptions_tenant_id", table_name="saas_subscriptions")
    op.drop_table("saas_subscriptions")

    op.drop_index("ix_saas_plans_is_active", table_name="saas_plans")
    op.drop_index("ix_saas_plans_plan_code", table_name="saas_plans")
    op.drop_table("saas_plans")

    op.drop_constraint("uq_customers_store_channel_sender", "customers", type_="unique")
    op.drop_index("ix_stores_billing_plan_code", table_name="stores")
    op.drop_column("stores", "billing_plan_code")
