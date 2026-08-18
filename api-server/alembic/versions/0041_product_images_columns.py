"""0041 — Add images + image_count to products (ORM/DB drift fix)

Revision ID: 0041_product_images_columns
Revises: 0040_order_status_returned_refunded
Create Date: 2026-06-27 00:00:00

RAISON:
  models/database.py Product déclare 2 colonnes jamais créées par une migration :
    - products.images        JSON nullable  — liste des URLs d'images (max 3-5 par plan)
    - products.image_count   Integer        — compteur rapide pour quota sans désérialiser JSON

  Sans ces colonnes, toute requête SELECT sur Product incluant ces champs
  échoue avec "column products.images does not exist" en production.
  Crash confirmé par Manus lors du test de déploiement (dashboard Admin Boutique).
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0041_product_images_columns"
down_revision = "0040_order_status_returned_refunded"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    try:
        cols = [c["name"] for c in inspect(bind).get_columns(table)]
        return column in cols
    except Exception:
        return False


def upgrade() -> None:
    if not _has_column("products", "images"):
        op.add_column("products", sa.Column(
            "images",
            sa.JSON(),
            nullable=True,
            comment="Liste des URLs d'images produit (max 3-5 selon plan)",
        ))

    if not _has_column("products", "image_count"):
        op.add_column("products", sa.Column(
            "image_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Compteur d'images — quota check sans désérialiser le JSON images",
        ))

    # Index on image_count for quota queries (stores with many images)
    try:
        op.create_index(
            "ix_products_store_image_count",
            "products",
            ["store_id", "image_count"],
        )
    except Exception:
        pass  # Already exists


def downgrade() -> None:
    try:
        op.drop_index("ix_products_store_image_count", table_name="products")
    except Exception:
        pass
    try:
        op.drop_column("products", "image_count")
    except Exception:
        pass
    try:
        op.drop_column("products", "images")
    except Exception:
        pass
