"""P1 — conversation FSM log, audit trail, store settings

Revision ID: 0002_p1_features
Revises: 0001_initial
Create Date: 2025-01-02 00:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = "0002_p1_features"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Conversation state log — full FSM trace per customer ──────────────────
    op.create_table(
        "conversation_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_state", sa.String(50), nullable=True),
        sa.Column("to_state", sa.String(50), nullable=False),
        sa.Column("trigger", sa.String(100), nullable=True),       # "text_message" | "image" | "button:confirm_order"
        sa.Column("payload", sa.JSON(), nullable=True),            # message content / vision result
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_conversation_logs_store_id", "conversation_logs", ["store_id"])
    op.create_index("ix_conversation_logs_customer_id", "conversation_logs", ["customer_id"])

    # ── Audit log — all admin actions ─────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),       # "product.create", "order.status_change", etc.
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(50), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_store_id", "audit_logs", ["store_id"])

    # ── Add conversation timeout tracking to customers ────────────────────────
    op.add_column("customers", sa.Column(
        "last_message_at", sa.DateTime(timezone=True), nullable=True
    ))

    # ── Add store-level settings columns ──────────────────────────────────────
    op.add_column("stores", sa.Column("timezone", sa.String(50), server_default="Africa/Tunis", nullable=True))
    op.add_column("stores", sa.Column("logo_url", sa.String(1000), nullable=True))
    op.add_column("stores", sa.Column("support_email", sa.String(255), nullable=True))
    op.add_column("stores", sa.Column("order_confirmation_msg", sa.Text(), nullable=True))
    op.add_column("stores", sa.Column("post_payment_msg", sa.Text(), nullable=True))
    op.add_column("stores", sa.Column("conversation_timeout_min", sa.Integer(), server_default="30", nullable=True))


def downgrade() -> None:
    op.drop_column("stores", "conversation_timeout_min")
    op.drop_column("stores", "post_payment_msg")
    op.drop_column("stores", "order_confirmation_msg")
    op.drop_column("stores", "support_email")
    op.drop_column("stores", "logo_url")
    op.drop_column("stores", "timezone")
    op.drop_column("customers", "last_message_at")
    op.drop_table("audit_logs")
    op.drop_table("conversation_logs")
