"""0015_store_public_fields — Champs publics boutique (description, adresse, contact, catégorie)

Revision ID: 0015_store_public_fields
Revises: 0014_social_ai_publisher
Create Date: 2026-04-26
"""
import sqlalchemy as sa

from alembic import op

revision = "0015_store_public_fields"
down_revision = "0014_social_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("description",   sa.Text,         nullable=True))
    op.add_column("stores", sa.Column("address",       sa.Text,         nullable=True))
    op.add_column("stores", sa.Column("phone_display", sa.String(30),   nullable=True))
    op.add_column("stores", sa.Column("website_url",   sa.String(500),  nullable=True))
    op.add_column("stores", sa.Column("category",      sa.String(64),   nullable=True))


def downgrade() -> None:
    for col in ["category", "website_url", "phone_display", "address", "description"]:
        op.drop_column("stores", col)
