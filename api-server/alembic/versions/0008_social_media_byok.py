"""0008_social_media_byok — Ajoute les colonnes BYOK réseaux sociaux (Instagram, Facebook, TikTok)

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-24
"""
import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Instagram BYOK
    op.add_column("stores", sa.Column("instagram_token_enc", sa.Text(), nullable=True))
    op.add_column("stores", sa.Column("instagram_account_id", sa.String(64), nullable=True))
    op.add_column("stores", sa.Column("instagram_username", sa.String(100), nullable=True))

    # Facebook BYOK
    op.add_column("stores", sa.Column("facebook_token_enc", sa.Text(), nullable=True))
    op.add_column("stores", sa.Column("facebook_page_id", sa.String(64), nullable=True))
    op.add_column("stores", sa.Column("facebook_page_name", sa.String(100), nullable=True))

    # TikTok BYOK
    op.add_column("stores", sa.Column("tiktok_token_enc", sa.Text(), nullable=True))
    op.add_column("stores", sa.Column("tiktok_open_id", sa.String(64), nullable=True))
    op.add_column("stores", sa.Column("tiktok_username", sa.String(100), nullable=True))


def downgrade() -> None:
    for col in [
        "instagram_token_enc", "instagram_account_id", "instagram_username",
        "facebook_token_enc", "facebook_page_id", "facebook_page_name",
        "tiktok_token_enc", "tiktok_open_id", "tiktok_username",
    ]:
        op.drop_column("stores", col)
