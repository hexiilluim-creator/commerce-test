"""0013_auto_parts_fields — Champs OEM lookup + stock sources + pièces auto

Revision ID: 0013_auto_parts_fields
Revises: 0012_saas_overlay_runtime
Create Date: 2026-04-26
"""
import sqlalchemy as sa

from alembic import op

revision = "0013_auto_parts_fields"
down_revision = "0012_saas_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("stock_source_type",       sa.String(30),  nullable=True))
    op.add_column("stores", sa.Column("stock_source_config_enc", sa.Text,        nullable=True))
    op.add_column("stores", sa.Column("tecdoc_api_key_enc",      sa.Text,        nullable=True))
    op.add_column("stores", sa.Column("tecdoc_provider_id",      sa.String(64),  nullable=True))
    op.add_column("stores", sa.Column("autoiso_api_key_enc",     sa.Text,        nullable=True))
    op.add_column("stores", sa.Column("nhtsa_enabled",           sa.Boolean,     nullable=False, server_default="true"))
    op.add_column("stores", sa.Column("auto_parts_mode",         sa.Boolean,     nullable=False, server_default="false"))


def downgrade() -> None:
    for col in ["auto_parts_mode", "nhtsa_enabled", "autoiso_api_key_enc",
                "tecdoc_provider_id", "tecdoc_api_key_enc",
                "stock_source_config_enc", "stock_source_type"]:
        op.drop_column("stores", col)
