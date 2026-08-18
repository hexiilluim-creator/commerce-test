"""0035_password_reset_tokens_session_cleanup

Révision  : 0035_password_reset_tokens_session_cleanup
Parent    : 0034_enterprise_omnicall

Changements :
  - Table  ``password_reset_tokens``  — tokens de reset mot de passe en DB
    (remplace/complète le stockage Redis — plus résilient, auditable)
  - Index composite  ix_prt_user_active  (user_id, used, expires_at)
    pour le nettoyage périodique et la vérification rapide de validité
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0035_password_reset_tokens"
down_revision = "0034_enterprise_omnicall"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token", sa.String(128), unique=True, nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_prt_user_active",
        "password_reset_tokens",
        ["user_id", "used", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_prt_user_active", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
