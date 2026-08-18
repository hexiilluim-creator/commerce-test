"""P0.4 — Tracking S3 keys pour les uploads (BLOCANT #4 FIX)

Revision ID: 0023_s3_upload_tracking
Revises: 0022_byok_openai_store_columns
Create Date: 2025-01-10 00:00:00

Raison : la migration vers S3 (upload_security.py + s3_storage.py) nécessite
de stocker la clé S3 (storage_key) ET le backend utilisé (s3/local) dans
les tables qui stockent des références de fichiers.

Compatibilité :
  - Base vide      : crée la table media_uploads -> OK
  - Base existante : ADD COLUMN nullable sur les tables existantes -> OK sans lock
  - Downgrade      : DROP TABLE / DROP COLUMN -> réversible
"""
import sqlalchemy as sa

from alembic import op

revision = "0023_s3_upload_tracking"
down_revision = "0022_byok_openai_store_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Table centralisée pour tracker tous les uploads
    op.create_table(
        "media_uploads",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False, comment="Clé S3 ou chemin FS local"),
        sa.Column("storage_backend", sa.String(16), nullable=False, server_default="local",
                  comment="'s3' | 'local'"),
        sa.Column("url", sa.Text(), nullable=True, comment="URL publique ou signée"),
        sa.Column("original_filename", sa.Text(), nullable=True),
        sa.Column("safe_filename", sa.String(100), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("extension", sa.String(16), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("upload_type", sa.String(32), nullable=True,
                  comment="'image' | 'document' | 'audio'"),
        sa.Column("entity_type", sa.String(64), nullable=True,
                  comment="Table référente : 'product', 'store_settings', etc."),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_media_uploads_store_id", "media_uploads", ["store_id"])
    op.create_index("ix_media_uploads_storage_backend", "media_uploads", ["storage_backend"])
    op.create_index("ix_media_uploads_entity", "media_uploads", ["entity_type", "entity_id"])

    # Ajouter colonnes S3 sur les tables existantes qui ont un champ image/fichier
    for table, col_name in [
        ("products", "image_storage_key"),
        ("stores",   "logo_storage_key"),
    ]:
        op.add_column(table, sa.Column(
            col_name, sa.Text(), nullable=True,
            comment="Clé S3 du fichier uploadé (migration vers S3)"
        ))
        op.add_column(table, sa.Column(
            col_name.replace("_key", "_backend"),
            sa.String(16), nullable=True, server_default="local"
        ))


def downgrade() -> None:
    for table, col_name in [
        ("stores",   "logo_storage_key"),
        ("products", "image_storage_key"),
    ]:
        try:
            op.drop_column(table, col_name.replace("_key", "_backend"))
            op.drop_column(table, col_name)
        except Exception:
            pass

    op.drop_index("ix_media_uploads_entity", table_name="media_uploads")
    op.drop_index("ix_media_uploads_storage_backend", table_name="media_uploads")
    op.drop_index("ix_media_uploads_store_id", table_name="media_uploads")
    op.drop_table("media_uploads")
