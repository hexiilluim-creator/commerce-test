"""0046_plan_e_visual_builder.py — Plan E1 migration.

Adds tables:
  - visual_builds
  - visual_build_assets
  - visual_build_reviews
  - visual_build_history
"""
import sqlalchemy as sa

from alembic import op

revision = "0046_plan_e_visual_builder"
down_revision = "0045_plan_b_promotions_marketing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visual_builds",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, nullable=False, index=True),
        sa.Column("product_id", sa.Integer, nullable=True, index=True),
        sa.Column("locale_default", sa.String(8), nullable=False, server_default="fr"),
        sa.Column("description_short", sa.Text, nullable=True),
        sa.Column("description_long", sa.Text, nullable=True),
        sa.Column("bullets", sa.JSON, nullable=True),
        sa.Column("seo_title", sa.String(140), nullable=True),
        sa.Column("seo_meta", sa.String(320), nullable=True),
        sa.Column("seo_keywords", sa.JSON, nullable=True),
        sa.Column("seo_og", sa.JSON, nullable=True),
        sa.Column("seo_score", sa.Integer, nullable=True, server_default="0"),
        sa.Column("translations", sa.JSON, nullable=True),
        sa.Column("glossary", sa.JSON, nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft", "pending_review", "approved", "rejected",
                "changes_requested", "published",
                name="visual_build_status",
            ),
            nullable=False, server_default="draft",
        ),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("store_id", "product_id", "locale_default",
                            name="uq_visual_build_product_locale"),
    )
    op.create_index("ix_visual_builds_store_status", "visual_builds", ["store_id", "status"])

    op.create_table(
        "visual_build_assets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("build_id", sa.Integer,
                  sa.ForeignKey("visual_builds.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("kind", sa.String(32), nullable=False, server_default="photo"),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("alt_text", sa.String(255), nullable=True),
        sa.Column("width", sa.Integer, nullable=True),
        sa.Column("height", sa.Integer, nullable=True),
        sa.Column("order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("ai_metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
    )

    op.create_table(
        "visual_build_reviews",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("build_id", sa.Integer,
                  sa.ForeignKey("visual_builds.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("reviewer_id", sa.Integer, nullable=True),
        sa.Column("decision", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("comments", sa.Text, nullable=True),
        sa.Column("diff", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
    )

    op.create_table(
        "visual_build_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, nullable=False, index=True),
        sa.Column("build_id", sa.Integer, nullable=False, index=True),
        sa.Column("actor_id", sa.Integer, nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("before", sa.JSON, nullable=True),
        sa.Column("after", sa.JSON, nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_visual_build_history_store_build",
                    "visual_build_history", ["store_id", "build_id"])


def downgrade() -> None:
    op.drop_index("ix_visual_build_history_store_build", table_name="visual_build_history")
    op.drop_table("visual_build_history")
    op.drop_table("visual_build_reviews")
    op.drop_table("visual_build_assets")
    op.drop_index("ix_visual_builds_store_status", table_name="visual_builds")
    op.drop_table("visual_builds")
