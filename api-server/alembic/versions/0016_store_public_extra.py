"""0016_store_public_extra — Horaires, Services, OSM et Liens Sociaux

Revision ID: 0016_store_public_extra
Revises: 0015_store_public_fields
Create Date: 2026-04-27
"""
import sqlalchemy as sa

from alembic import op

revision = "0016_store_public_extra"
down_revision = "0015_store_public_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("opening_hours", sa.JSON,   nullable=True))
    op.add_column("stores", sa.Column("services",      sa.JSON,   nullable=True))
    op.add_column("stores", sa.Column("latitude",      sa.Float,  nullable=True))
    op.add_column("stores", sa.Column("longitude",     sa.Float,  nullable=True))
    op.add_column("stores", sa.Column("social_links",  sa.JSON,   nullable=True))


def downgrade() -> None:
    for col in ["social_links", "longitude", "latitude", "services", "opening_hours"]:
        op.drop_column("stores", col)
