"""Sprint 1 — 5 bloquants corrigés en DB

Revision ID: 0003_sprint1_blockers
Revises: 0002_p1_features
Create Date: 2025-01-03 00:00:00

Changes:
  - products.stock_reserved INT (atomic stock management)
  - stores.whatsapp_access_token_enc TEXT (per-store WA token)
  - stores.whatsapp_phone_number_id TEXT (per-store phone_number_id)
  - composite indexes: orders(store_id,status), customers(store_id,whatsapp_phone)
  - customers: unique constraint (store_id, whatsapp_phone) — prevents duplicate upsert

Compatibility (P0):
  - SQLite ne supporte pas ALTER TABLE pour ajouter une contrainte UNIQUE
    en mode "alter constraint". On utilise donc `batch_alter_table()` sur SQLite
    et `create_unique_constraint()` sur les autres SGBD.
  - Les `drop_index(..., table_name=...)` sont harmonisés.
"""
import sqlalchemy as sa

from alembic import op

revision = "0003_sprint1_blockers"
down_revision = "0002_p1_features"
branch_labels = None
depends_on = None


def _is_sqlite() -> bool:
    bind = op.get_bind()
    try:
        return bind.dialect.name == "sqlite"
    except Exception:
        return False


def upgrade() -> None:
    # ── E19: stock_reserved for atomic stock management ───────────────────────
    op.add_column(
        "products",
        sa.Column("stock_reserved", sa.Integer(), nullable=False, server_default="0"),
    )

    # ── E23: per-store WhatsApp token + phone_number_id ───────────────────────
    op.add_column("stores", sa.Column("whatsapp_access_token_enc", sa.Text(), nullable=True))
    op.add_column("stores", sa.Column("whatsapp_phone_number_id", sa.String(64), nullable=True))

    # ── E22: unique constraint on (store_id, whatsapp_phone) ──────────────────
    if _is_sqlite():
        # SQLite : passer par batch_alter_table pour créer la contrainte unique
        with op.batch_alter_table("customers", schema=None) as batch_op:
            batch_op.create_unique_constraint(
                "uq_customers_store_phone",
                ["store_id", "whatsapp_phone"],
            )
    else:
        op.create_unique_constraint(
            "uq_customers_store_phone",
            "customers",
            ["store_id", "whatsapp_phone"],
        )

    # ── E14: composite indexes for high-frequency queries ─────────────────────
    op.create_index("idx_orders_store_status", "orders", ["store_id", "status"])
    op.create_index("idx_orders_store_created", "orders", ["store_id", "created_at"])
    op.create_index("idx_customers_store_phone", "customers", ["store_id", "whatsapp_phone"])
    op.create_index("idx_wa_messages_store_phone", "whatsapp_messages", ["store_id", "from_phone"])
    op.create_index("idx_products_store_active", "products", ["store_id", "is_active"])
    op.create_index("idx_audit_store_created", "audit_logs", ["store_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_audit_store_created", table_name="audit_logs")
    op.drop_index("idx_products_store_active", table_name="products")
    op.drop_index("idx_wa_messages_store_phone", table_name="whatsapp_messages")
    op.drop_index("idx_customers_store_phone", table_name="customers")
    op.drop_index("idx_orders_store_created", table_name="orders")
    op.drop_index("idx_orders_store_status", table_name="orders")

    if _is_sqlite():
        with op.batch_alter_table("customers", schema=None) as batch_op:
            batch_op.drop_constraint("uq_customers_store_phone", type_="unique")
    else:
        op.drop_constraint("uq_customers_store_phone", "customers", type_="unique")

    op.drop_column("stores", "whatsapp_phone_number_id")
    op.drop_column("stores", "whatsapp_access_token_enc")
    op.drop_column("products", "stock_reserved")
