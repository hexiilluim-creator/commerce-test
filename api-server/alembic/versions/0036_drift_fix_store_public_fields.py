"""0036_drift_fix_store_public_fields — Fix schema drift: add columns present in ORM but missing in migrations

Revision ID: 0036_drift_fix_store_public_fields
Revises: b09e4521bd0c
Create Date: 2026-06-24

Columns present in models/database.py Store model but NEVER added by any migration:
  - stores.banner_url            (String 1000, nullable)
  - stores.messenger_page_id     (String 100, nullable)
  - stores.instagram_handle      (String 100, nullable)
  - stores.tiktok_handle         (String 100, nullable)
  - stores.post_payment_msg      (Text, nullable)

All operations are idempotent: if the column already exists (added manually in prod),
the op is skipped.
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0036_drift_fix_store_public_fields"
down_revision = "b09e4521bd0c"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """Idempotency helper — check if a column already exists."""
    bind = op.get_bind()
    insp = inspect(bind)
    try:
        cols = [c["name"] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols


def upgrade() -> None:
    # ── stores.banner_url ─────────────────────────────────────────────────────
    if not _has_column("stores", "banner_url"):
        op.add_column(
            "stores",
            sa.Column("banner_url", sa.String(length=1000), nullable=True),
        )

    # ── stores.messenger_page_id ───────────────────────────────────────────────
    if not _has_column("stores", "messenger_page_id"):
        op.add_column(
            "stores",
            sa.Column("messenger_page_id", sa.String(length=100), nullable=True),
        )

    # ── stores.instagram_handle ────────────────────────────────────────────────
    if not _has_column("stores", "instagram_handle"):
        op.add_column(
            "stores",
            sa.Column("instagram_handle", sa.String(length=100), nullable=True),
        )

    # ── stores.tiktok_handle ──────────────────────────────────────────────────
    if not _has_column("stores", "tiktok_handle"):
        op.add_column(
            "stores",
            sa.Column("tiktok_handle", sa.String(length=100), nullable=True),
        )

    # ── stores.post_payment_msg ───────────────────────────────────────────────
    if not _has_column("stores", "post_payment_msg"):
        op.add_column(
            "stores",
            sa.Column("post_payment_msg", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    for col in ["post_payment_msg", "tiktok_handle", "instagram_handle",
                "messenger_page_id", "banner_url"]:
        if _has_column("stores", col):
            op.drop_column("stores", col)
