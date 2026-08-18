"""0045_plan_b_promotions_marketing

Revision ID: 0045_plan_b_promotions_marketing
Revises: 0044_plan_a_tax_and_billing
Create Date: 2026-06-28

Plan B — Promotions & marketing :
- infrastructure campagnes / promotions / coupons / règles / usages
- remises appliquées sur commandes et liens de paiement
"""
import sqlalchemy as sa

from alembic import op

revision = "0045_plan_b_promotions_marketing"
down_revision = "0044_plan_a_tax_and_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("discount_amount", sa.Numeric(12, 4), nullable=True))
    op.add_column("orders", sa.Column("promotion_codes", sa.JSON(), nullable=True))
    op.add_column("orders", sa.Column("promotion_breakdown", sa.JSON(), nullable=True))

    op.add_column("payment_links", sa.Column("discount_amount", sa.Numeric(12, 4), nullable=True))
    op.add_column("payment_links", sa.Column("promotion_codes", sa.JSON(), nullable=True))
    op.add_column("payment_links", sa.Column("promotion_breakdown", sa.JSON(), nullable=True))

    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("channel", sa.String(length=50), nullable=True),
        sa.Column("trigger_type", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_campaigns_store_id"), "campaigns", ["store_id"])
    op.create_index(op.f("ix_campaigns_status"), "campaigns", ["status"])
    op.create_index(op.f("ix_campaigns_start_at"), "campaigns", ["start_at"])
    op.create_index(op.f("ix_campaigns_end_at"), "campaigns", ["end_at"])

    op.create_table(
        "promotions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("promotion_type", sa.String(length=30), nullable=False, server_default="automatic"),
        sa.Column("discount_type", sa.String(length=30), nullable=False, server_default="percentage"),
        sa.Column("discount_value", sa.Numeric(12, 4), nullable=True),
        sa.Column("applies_to", sa.String(length=30), nullable=False, server_default="all"),
        sa.Column("eligible_product_ids", sa.JSON(), nullable=True),
        sa.Column("eligible_categories", sa.JSON(), nullable=True),
        sa.Column("eligible_brands", sa.JSON(), nullable=True),
        sa.Column("gift_product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("gift_name", sa.String(length=255), nullable=True),
        sa.Column("gift_quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("stackable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("customer_segment", sa.String(length=30), nullable=True),
        sa.Column("country_codes", sa.JSON(), nullable=True),
        sa.Column("channel_codes", sa.JSON(), nullable=True),
        sa.Column("max_global_uses", sa.Integer(), nullable=True),
        sa.Column("max_uses_per_customer", sa.Integer(), nullable=True),
        sa.Column("max_discount_amount", sa.Numeric(12, 4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_promotions_store_id"), "promotions", ["store_id"])
    op.create_index(op.f("ix_promotions_campaign_id"), "promotions", ["campaign_id"])
    op.create_index(op.f("ix_promotions_promotion_type"), "promotions", ["promotion_type"])
    op.create_index(op.f("ix_promotions_priority"), "promotions", ["priority"])
    op.create_index(op.f("ix_promotions_start_at"), "promotions", ["start_at"])
    op.create_index(op.f("ix_promotions_end_at"), "promotions", ["end_at"])
    op.create_index(op.f("ix_promotions_is_active"), "promotions", ["is_active"])

    op.create_table(
        "promotion_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("promotion_id", sa.Integer(), sa.ForeignKey("promotions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("rule_type", sa.String(length=50), nullable=False, server_default="conditions"),
        sa.Column("conditions", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_promotion_rules_store_id"), "promotion_rules", ["store_id"])
    op.create_index(op.f("ix_promotion_rules_promotion_id"), "promotion_rules", ["promotion_id"])

    op.create_table(
        "coupons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("promotion_id", sa.Integer(), sa.ForeignKey("promotions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("coupon_kind", sa.String(length=20), nullable=False, server_default="multi"),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("redemptions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("per_customer_limit", sa.Integer(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("store_id", "code", name="uq_coupons_store_code"),
    )
    op.create_index(op.f("ix_coupons_store_id"), "coupons", ["store_id"])
    op.create_index(op.f("ix_coupons_promotion_id"), "coupons", ["promotion_id"])
    op.create_index(op.f("ix_coupons_starts_at"), "coupons", ["starts_at"])
    op.create_index(op.f("ix_coupons_ends_at"), "coupons", ["ends_at"])
    op.create_index(op.f("ix_coupons_is_active"), "coupons", ["is_active"])

    op.create_table(
        "promotion_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("promotion_id", sa.Integer(), sa.ForeignKey("promotions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("coupon_id", sa.Integer(), sa.ForeignKey("coupons.id", ondelete="SET NULL"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payment_link_id", sa.Integer(), sa.ForeignKey("payment_links.id", ondelete="SET NULL"), nullable=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("customer_email", sa.String(length=255), nullable=True),
        sa.Column("customer_phone", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="applied"),
        sa.Column("discount_amount", sa.Numeric(12, 4), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_promotion_usage_store_id"), "promotion_usage", ["store_id"])
    op.create_index(op.f("ix_promotion_usage_promotion_id"), "promotion_usage", ["promotion_id"])
    op.create_index(op.f("ix_promotion_usage_coupon_id"), "promotion_usage", ["coupon_id"])
    op.create_index(op.f("ix_promotion_usage_order_id"), "promotion_usage", ["order_id"])
    op.create_index(op.f("ix_promotion_usage_payment_link_id"), "promotion_usage", ["payment_link_id"])
    op.create_index(op.f("ix_promotion_usage_customer_id"), "promotion_usage", ["customer_id"])
    op.create_index(op.f("ix_promotion_usage_status"), "promotion_usage", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_promotion_usage_status"), table_name="promotion_usage")
    op.drop_index(op.f("ix_promotion_usage_customer_id"), table_name="promotion_usage")
    op.drop_index(op.f("ix_promotion_usage_payment_link_id"), table_name="promotion_usage")
    op.drop_index(op.f("ix_promotion_usage_order_id"), table_name="promotion_usage")
    op.drop_index(op.f("ix_promotion_usage_coupon_id"), table_name="promotion_usage")
    op.drop_index(op.f("ix_promotion_usage_promotion_id"), table_name="promotion_usage")
    op.drop_index(op.f("ix_promotion_usage_store_id"), table_name="promotion_usage")
    op.drop_table("promotion_usage")

    op.drop_index(op.f("ix_coupons_is_active"), table_name="coupons")
    op.drop_index(op.f("ix_coupons_ends_at"), table_name="coupons")
    op.drop_index(op.f("ix_coupons_starts_at"), table_name="coupons")
    op.drop_index(op.f("ix_coupons_promotion_id"), table_name="coupons")
    op.drop_index(op.f("ix_coupons_store_id"), table_name="coupons")
    op.drop_table("coupons")

    op.drop_index(op.f("ix_promotion_rules_promotion_id"), table_name="promotion_rules")
    op.drop_index(op.f("ix_promotion_rules_store_id"), table_name="promotion_rules")
    op.drop_table("promotion_rules")

    op.drop_index(op.f("ix_promotions_is_active"), table_name="promotions")
    op.drop_index(op.f("ix_promotions_end_at"), table_name="promotions")
    op.drop_index(op.f("ix_promotions_start_at"), table_name="promotions")
    op.drop_index(op.f("ix_promotions_priority"), table_name="promotions")
    op.drop_index(op.f("ix_promotions_promotion_type"), table_name="promotions")
    op.drop_index(op.f("ix_promotions_campaign_id"), table_name="promotions")
    op.drop_index(op.f("ix_promotions_store_id"), table_name="promotions")
    op.drop_table("promotions")

    op.drop_index(op.f("ix_campaigns_end_at"), table_name="campaigns")
    op.drop_index(op.f("ix_campaigns_start_at"), table_name="campaigns")
    op.drop_index(op.f("ix_campaigns_status"), table_name="campaigns")
    op.drop_index(op.f("ix_campaigns_store_id"), table_name="campaigns")
    op.drop_table("campaigns")

    op.drop_column("payment_links", "promotion_breakdown")
    op.drop_column("payment_links", "promotion_codes")
    op.drop_column("payment_links", "discount_amount")

    op.drop_column("orders", "promotion_breakdown")
    op.drop_column("orders", "promotion_codes")
    op.drop_column("orders", "discount_amount")
