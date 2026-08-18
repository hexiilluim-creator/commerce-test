"""0014_social_ai_publisher — Tables configuration IA social + historique posts

Revision ID: 0014_social_ai_publisher
Revises: 0013_auto_parts_fields
Create Date: 2026-04-26
"""
import sqlalchemy as sa

from alembic import op

revision = "0014_social_ai"
down_revision = "0013_auto_parts_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── social_post_configs : préférences IA par store ─────────────────────
    op.create_table(
        "social_post_configs",
        sa.Column("id",               sa.Integer,     primary_key=True),
        sa.Column("store_id",         sa.Integer,     sa.ForeignKey("stores.id", ondelete="CASCADE"), unique=True, nullable=False),
        # Identité de marque
        sa.Column("brand_name",       sa.String(128), nullable=True),
        sa.Column("brand_voice",      sa.String(32),  nullable=False, server_default="professionnel"),
        sa.Column("default_language", sa.String(10),  nullable=False, server_default="fr"),
        sa.Column("hashtags",         sa.Text,        nullable=True),   # JSON list
        sa.Column("emoji_style",      sa.String(16),  nullable=False, server_default="moderate"),
        # Style image DALL-E
        sa.Column("image_style",      sa.String(128), nullable=False, server_default="commercial product photo, clean background, professional"),
        sa.Column("image_colors",     sa.String(128), nullable=True),
        sa.Column("watermark_text",   sa.String(64),  nullable=True),
        # Réseaux actifs
        sa.Column("networks_enabled", sa.Text,        nullable=False, server_default='["instagram","facebook"]'),
        # Timing automatique
        sa.Column("auto_schedule",    sa.Boolean,     nullable=False, server_default="false"),
        sa.Column("post_times",       sa.Text,        nullable=True),   # JSON ["09:00","18:00"]
        sa.Column("post_days",        sa.Text,        nullable=True),   # JSON [1,2,3,4,5] (lundi=1)
        sa.Column("timezone",         sa.String(64),  nullable=False, server_default="Africa/Tunis"),
        sa.Column("max_posts_per_day",sa.Integer,     nullable=False, server_default="3"),
        sa.Column("created_at",       sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",       sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_social_post_configs_store_id", "social_post_configs", ["store_id"])

    # ── social_posts : historique de chaque publication ────────────────────
    op.create_table(
        "social_posts",
        sa.Column("id",           sa.Integer,     primary_key=True),
        sa.Column("store_id",     sa.Integer,     sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("network",      sa.String(20),  nullable=False),   # instagram|facebook|tiktok
        sa.Column("post_type",    sa.String(20),  nullable=False, server_default="post"),  # post|story|reel
        sa.Column("status",       sa.String(20),  nullable=False, server_default="pending"),  # pending|published|failed|scheduled|cancelled
        sa.Column("caption",      sa.Text,        nullable=True),
        sa.Column("image_url",    sa.Text,        nullable=True),    # URL DALL-E ou externe
        sa.Column("image_prompt", sa.Text,        nullable=True),    # Prompt DALL-E utilisé
        sa.Column("external_post_id", sa.String(128), nullable=True),  # ID retourné par le réseau
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error",        sa.Text,        nullable=True),
        sa.Column("source",       sa.String(32),  nullable=False, server_default="manual"),  # manual|ai_auto|scheduled
        sa.Column("product_id",   sa.Integer,     nullable=True),
        sa.Column("celery_task_id", sa.String(128), nullable=True),
        sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_social_posts_store_id",   "social_posts", ["store_id"])
    op.create_index("ix_social_posts_status",     "social_posts", ["status"])
    op.create_index("ix_social_posts_scheduled",  "social_posts", ["scheduled_at"])
    op.create_index("ix_social_posts_network",    "social_posts", ["network"])


def downgrade() -> None:
    op.drop_table("social_posts")
    op.drop_table("social_post_configs")
