"""0030 — CustomerIdentity + ContactEndpoint + omnichannel columns

Revision ID: 0030
Revises: 0029_remove_byok_openai_columns
Create Date: 2025-06-14

Changes:
  - Table customer_identities : identité client unifiée cross-canal
  - Table contact_endpoints   : un endpoint par canal (WhatsApp/IG/FB/TT)
  - customers.social_sender_id (canal social)
  - customers.channel (whatsapp|instagram|facebook|tiktok)
  - customers.display_name
  - customers.social_sender_id index
  - stores.owner_phone, stores.billing_status, stores.language
  - stores.whatsapp_access_token_enc (per-store credentials)
  - knowledge_chunks table (RAG vectors)
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0030"
down_revision = "0029_remove_byok_openai_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. customer_identities ────────────────────────────────────────────
    op.create_table(
        "customer_identities",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("merged_customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone_normalized", sa.String(30), nullable=True),
        sa.Column("ltv", sa.Numeric(12, 3), server_default="0"),
        sa.Column("segment", sa.String(20), server_default="standard"),
        sa.Column("extra_data", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_customer_identities_store_id", "customer_identities", ["store_id"])
    op.create_index("ix_customer_identities_phone", "customer_identities", ["phone_normalized"], postgresql_where=sa.text("phone_normalized IS NOT NULL"))

    # ── 2. contact_endpoints ─────────────────────────────────────────────
    op.create_table(
        "contact_endpoints",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("identity_id", sa.BigInteger(), sa.ForeignKey("customer_identities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),   # whatsapp|instagram|facebook|tiktok
        sa.Column("external_id", sa.String(200), nullable=False),  # phone/PSID/IGSID/TT open_id
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("opted_out", sa.Boolean(), server_default="false"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("store_id", "channel", "external_id", name="uq_contact_endpoints_store_channel_id"),
    )
    op.create_index("ix_contact_endpoints_identity_id", "contact_endpoints", ["identity_id"])
    op.create_index("ix_contact_endpoints_customer_id", "contact_endpoints", ["customer_id"])
    op.create_index("ix_contact_endpoints_channel_external", "contact_endpoints", ["channel", "external_id"])

    # ── 3. Colonnes customers ─────────────────────────────────────────────
    _add_column_if_not_exists(conn, "customers", "social_sender_id", "VARCHAR(200)")
    _add_column_if_not_exists(conn, "customers", "channel", "VARCHAR(20) DEFAULT 'whatsapp'")
    _add_column_if_not_exists(conn, "customers", "display_name", "VARCHAR(200)")
    _add_column_if_not_exists(conn, "customers", "opted_out_recovery", "BOOLEAN DEFAULT false")

    # Index conditionnel sur social_sender_id
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_customers_social_sender
        ON customers (store_id, channel, social_sender_id)
        WHERE social_sender_id IS NOT NULL
    """))

    # ── 4. Colonnes stores ────────────────────────────────────────────────
    _add_column_if_not_exists(conn, "stores", "owner_phone", "VARCHAR(30)")
    _add_column_if_not_exists(conn, "stores", "billing_status", "VARCHAR(20) DEFAULT 'active'")
    _add_column_if_not_exists(conn, "stores", "language", "VARCHAR(10) DEFAULT 'fr'")
    _add_column_if_not_exists(conn, "stores", "whatsapp_access_token_enc", "TEXT")
    _add_column_if_not_exists(conn, "stores", "facebook_token_enc", "TEXT")
    _add_column_if_not_exists(conn, "stores", "instagram_token_enc", "TEXT")
    _add_column_if_not_exists(conn, "stores", "instagram_account_id", "VARCHAR(50)")
    _add_column_if_not_exists(conn, "stores", "tiktok_token_enc", "TEXT")
    _add_column_if_not_exists(conn, "stores", "support_email", "VARCHAR(320)")
    _add_column_if_not_exists(conn, "stores", "post_payment_msg", "TEXT")

    # ── 5. knowledge_chunks (RAG vectors) ─────────────────────────────────
    # Nécessite pgvector installé (extension vecteur)
    try:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        op.create_table(
            "knowledge_chunks",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("content_hash", sa.String(32), nullable=False),
            sa.Column("source", sa.String(200), nullable=True),
            sa.Column("embedding", sa.Text(), nullable=True),  # JSON list si pas pgvector vector type
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("store_id", "content_hash", name="uq_knowledge_chunks_store_hash"),
        )
        op.create_index("ix_knowledge_chunks_store_id", "knowledge_chunks", ["store_id"])
    except Exception as e:
        print(f"[WARN] knowledge_chunks creation skipped: {e}")

    # ── 6. Migrer données existantes ──────────────────────────────────────
    # Définir channel='whatsapp' pour les customers existants sans channel
    conn.execute(sa.text("""
        UPDATE customers SET channel = 'whatsapp'
        WHERE channel IS NULL AND whatsapp_phone IS NOT NULL
    """))

    # Créer une CustomerIdentity pour chaque customer existant ayant un téléphone
    conn.execute(sa.text("""
        INSERT INTO customer_identities (store_id, merged_customer_id, phone_normalized, created_at, updated_at)
        SELECT DISTINCT ON (store_id, whatsapp_phone)
            store_id,
            id AS merged_customer_id,
            whatsapp_phone AS phone_normalized,
            created_at,
            NOW()
        FROM customers
        WHERE whatsapp_phone IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM customer_identities ci
              WHERE ci.store_id = customers.store_id
                AND ci.phone_normalized = customers.whatsapp_phone
          )
        ON CONFLICT DO NOTHING
    """))

    print("[0030] Migration CustomerIdentity + ContactEndpoint terminée.")


def downgrade() -> None:
    conn = op.get_bind()

    try:
        op.drop_table("knowledge_chunks")
    except Exception:
        pass

    op.drop_table("contact_endpoints")
    op.drop_table("customer_identities")

    for col in ["social_sender_id", "channel", "display_name", "opted_out_recovery"]:
        _drop_column_if_exists(conn, "customers", col)

    for col in ["owner_phone", "billing_status", "language", "whatsapp_access_token_enc",
                "facebook_token_enc", "instagram_token_enc", "instagram_account_id",
                "tiktok_token_enc", "support_email", "post_payment_msg"]:
        _drop_column_if_exists(conn, "stores", col)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _add_column_if_not_exists(conn, table: str, column: str, col_type: str) -> None:
    exists = conn.execute(sa.text(f"""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = '{table}' AND column_name = '{column}'
    """)).fetchone()
    if not exists:
        conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))


def _drop_column_if_exists(conn, table: str, column: str) -> None:
    exists = conn.execute(sa.text(f"""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = '{table}' AND column_name = '{column}'
    """)).fetchone()
    if exists:
        conn.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN {column}"))
