"""0048_plan_e_loyalty_ia.py — Plan E3 migration.

Adds tables:
  - segment_definitions
  - customer_segment_members
  - loyalty_recommendations
  - loyalty_churn_scores
  - loyalty_ia_model_versions
"""
import sqlalchemy as sa

from alembic import op

revision = "0048_plan_e_loyalty_ia"
down_revision = "0047_plan_e_predictive_restocking"
branch_labels = ("plan_e",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "segment_definitions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("segment_type",
                  sa.Enum("rfm", "behavioral", "lifecycle", "custom",
                          name="segment_type"),
                  nullable=False, server_default="rfm"),
        sa.Column("rules", sa.JSON, nullable=True),
        sa.Column("color", sa.String(16), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("store_id", "name", name="uq_segment_name_per_store"),
    )

    op.create_table(
        "customer_segment_members",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, nullable=False, index=True),
        sa.Column("customer_id", sa.Integer, nullable=False, index=True),
        sa.Column("segment_id", sa.Integer, nullable=False, index=True),
        sa.Column("score", sa.Float, nullable=False, server_default="0"),
        sa.Column("last_computed_at", sa.DateTime, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("store_id", "customer_id", "segment_id",
                            name="uq_customer_segment"),
    )
    op.create_index("ix_csm_segment_score", "customer_segment_members",
                    ["segment_id", "score"])

    op.create_table(
        "loyalty_recommendations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, nullable=False, index=True),
        sa.Column("customer_id", sa.Integer, nullable=False, index=True),
        sa.Column("variant_id", sa.Integer, nullable=True),
        sa.Column("sku", sa.String(80), nullable=True),
        sa.Column("score", sa.Float, nullable=False, server_default="0"),
        sa.Column("reason", sa.String(255), nullable=False, server_default="co_occurrence"),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_lr_store_customer_score", "loyalty_recommendations",
                    ["store_id", "customer_id", "score"])

    op.create_table(
        "loyalty_churn_scores",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, nullable=False, index=True),
        sa.Column("customer_id", sa.Integer, nullable=False, index=True),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("risk_band", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("drivers", sa.JSON, nullable=True),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("computed_at", sa.DateTime, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_churn_band", "loyalty_churn_scores", ["store_id", "risk_band"])
    op.create_index("ix_churn_customer", "loyalty_churn_scores", ["store_id", "customer_id"])

    op.create_table(
        "loyalty_ia_model_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("state",
                  sa.Enum("candidate", "staging", "production", "archived",
                          name="loyalty_ia_model_state"),
                  nullable=False, server_default="candidate"),
        sa.Column("metrics", sa.JSON, nullable=True),
        sa.Column("params", sa.JSON, nullable=True),
        sa.Column("promoted_at", sa.DateTime, nullable=True),
        sa.Column("promoted_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("store_id", "name", "version", name="uq_lia_model_version"),
    )


def downgrade() -> None:
    op.drop_table("loyalty_ia_model_versions")
    op.drop_index("ix_churn_customer", table_name="loyalty_churn_scores")
    op.drop_index("ix_churn_band", table_name="loyalty_churn_scores")
    op.drop_table("loyalty_churn_scores")
    op.drop_index("ix_lr_store_customer_score", table_name="loyalty_recommendations")
    op.drop_table("loyalty_recommendations")
    op.drop_index("ix_csm_segment_score", table_name="customer_segment_members")
    op.drop_table("customer_segment_members")
    op.drop_table("segment_definitions")
