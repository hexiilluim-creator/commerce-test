"""P0.2 — Matérialiser colonnes BYOK OpenAI + extra_config dans stores

Revision ID: 0022_byok_openai_store_columns
Revises: 0021_composite_indexes_1k_tenants
Create Date: 2025-01-06 00:00:00

Raison : les colonnes openai_* étaient référencées dans settings.py via getattr(store, ..., None)
mais absentes du schéma DB -> BYOK silencieusement non fonctionnel.

Compatibilité :
  - Base vide      : upgrade crée les colonnes avec defaults -> OK
  - Base existante : ALTER TABLE ADD COLUMN avec default -> OK, pas de lock
  - Downgrade      : DROP COLUMN -> réversible (perte de données clés BYOK)
"""
import sqlalchemy as sa

from alembic import op

revision = "0022_byok_openai_store_columns"
down_revision = "0021_composite_indexes_1k_tenants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── BYOK OpenAI columns ───────────────────────────────────────────────────
    op.add_column("stores", sa.Column(
        "openai_api_key_enc", sa.Text(), nullable=True
    ))
    op.add_column("stores", sa.Column(
        "openai_api_key_last4", sa.String(4), nullable=True
    ))
    op.add_column("stores", sa.Column(
        "openai_byok_enabled", sa.Boolean(),
        nullable=False, server_default=sa.text("false")
    ))
    op.add_column("stores", sa.Column(
        "openai_model_override", sa.String(64), nullable=True
    ))
    op.add_column("stores", sa.Column(
        "openai_key_updated_at", sa.DateTime(timezone=True), nullable=True
    ))

    # ── extra_config JSON — catch-all for future integrations ─────────────────
    op.add_column("stores", sa.Column(
        "extra_config", sa.JSON(), nullable=True
    ))

    # Optional index on byok_enabled for admin queries
    # (find all tenants using BYOK — useful for billing)
    op.create_index(
        "ix_stores_byok_enabled",
        "stores",
        ["openai_byok_enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_stores_byok_enabled", table_name="stores")
    op.drop_column("stores", "extra_config")
    op.drop_column("stores", "openai_key_updated_at")
    op.drop_column("stores", "openai_model_override")
    op.drop_column("stores", "openai_byok_enabled")
    op.drop_column("stores", "openai_api_key_last4")
    op.drop_column("stores", "openai_api_key_enc")
