"""0047_plan_e_predictive_restocking.py — Plan E2 migration.

Adds tables:
  - restock_forecasts
  - restock_alerts
  - restock_suggestions
  - restock_seasonality
"""
import sqlalchemy as sa

from alembic import op

revision = "0047_plan_e_predictive_restocking"
down_revision = "0046_plan_e_visual_builder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("option_values", sa.JSON(), nullable=True),
        sa.Column("price_override", sa.Numeric(12, 4), nullable=True),
        sa.Column("stock_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stock_reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("store_id", "sku", name="uq_product_variants_store_sku"),
    )
    op.create_index("ix_product_variants_store_product", "product_variants", ["store_id", "product_id"])

    op.create_table(
        "restock_forecasts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, nullable=False, index=True),
        sa.Column("variant_id", sa.Integer, nullable=True, index=True),
        sa.Column("sku", sa.String(80), nullable=True, index=True),
        sa.Column("forecast_date", sa.Date, nullable=False, index=True),
        sa.Column("horizon_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("predicted_qty", sa.Float, nullable=False),
        sa.Column("lower_bound", sa.Float, nullable=False),
        sa.Column("upper_bound", sa.Float, nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("computed_at", sa.DateTime, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_restock_forecasts_store_sku_date",
                    "restock_forecasts", ["store_id", "sku", "forecast_date"])

    op.create_table(
        "restock_alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, nullable=False, index=True),
        sa.Column("variant_id", sa.Integer, nullable=True, index=True),
        sa.Column("sku", sa.String(80), nullable=True, index=True),
        sa.Column("alert_type", sa.String(32), nullable=False),
        sa.Column("severity",
                  sa.Enum("info", "low", "medium", "high", "critical",
                          name="restock_alert_severity"),
                  nullable=False, server_default="medium"),
        sa.Column("status",
                  sa.Enum("open", "acknowledged", "resolved", "snoozed",
                          name="restock_alert_status"),
                  nullable=False, server_default="open", index=True),
        sa.Column("predicted_stockout_date", sa.Date, nullable=True),
        sa.Column("on_hand", sa.Float, nullable=True),
        sa.Column("lead_time_days", sa.Integer, nullable=True),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "restock_suggestions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, nullable=False, index=True),
        sa.Column("variant_id", sa.Integer,
                  sa.ForeignKey("product_variants.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("sku", sa.String(80), nullable=False, index=True),
        sa.Column("qty", sa.Numeric(18, 3), nullable=False),
        sa.Column("supplier", sa.String(255), nullable=True),
        sa.Column("lead_time_days", sa.Integer, nullable=False, server_default="7"),
        sa.Column("unit_cost", sa.Numeric(18, 2), nullable=True),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("status",
                  sa.Enum("pending", "approved", "rejected", "ordered", "received",
                          name="restock_suggestion_status"),
                  nullable=False, server_default="pending", index=True),
        sa.Column("reviewer_id", sa.Integer, nullable=True),
        sa.Column("reviewed_at", sa.DateTime, nullable=True),
        sa.Column("review_note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
    )

    op.create_table(
        "restock_seasonality",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, nullable=False, index=True),
        sa.Column("sku", sa.String(80), nullable=False, index=True),
        sa.Column("weekly_profile", sa.JSON, nullable=True),
        sa.Column("monthly_profile", sa.JSON, nullable=True),
        sa.Column("yearly_profile", sa.JSON, nullable=True),
        sa.Column("trend_slope", sa.Float, nullable=False, server_default="0"),
        sa.Column("residual_std", sa.Float, nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime, server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("restock_seasonality")
    op.drop_table("restock_suggestions")
    op.drop_table("restock_alerts")
    op.drop_index("ix_restock_forecasts_store_sku_date", table_name="restock_forecasts")
    op.drop_table("restock_forecasts")
    op.drop_index("ix_product_variants_store_product", table_name="product_variants")
    op.drop_table("product_variants")
