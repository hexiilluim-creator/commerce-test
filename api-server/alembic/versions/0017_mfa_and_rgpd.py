"""0017_mfa_and_rgpd — MFA TOTP et RGPD Delete/Export
Revision ID: 0017_mfa_and_rgpd
Revises: 0016_store_public_extra
Create Date: 2026-04-27
"""
import sqlalchemy as sa

from alembic import op

revision = "0017_mfa_and_rgpd"
down_revision = "0016_store_public_extra"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("users", sa.Column("mfa_secret", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), server_default="false", nullable=False))
    
def downgrade() -> None:
    op.drop_column("users", "mfa_enabled")
    op.drop_column("users", "mfa_secret")
